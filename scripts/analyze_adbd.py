import struct
from capstone import *

path="rootfs/usr/bin/adbd"; d=open(path,'rb').read()
e_shoff=struct.unpack_from('<I',d,0x20)[0]
e_shentsize=struct.unpack_from('<H',d,0x2E)[0]
e_shnum=struct.unpack_from('<H',d,0x30)[0]
e_shstrndx=struct.unpack_from('<H',d,0x32)[0]
def sh(i):
    o=e_shoff+i*e_shentsize
    n,t,f,a,off,sz,lnk,info,align,ent=struct.unpack_from('<IIIIIIIIII',d,o)
    return dict(n=n,typ=t,addr=a,off=off,size=sz,link=lnk,ent=ent)
raw=[sh(i) for i in range(e_shnum)]
st=raw[e_shstrndx]
def nm(x):
    s=st['off']+x; return d[s:d.index(b'\0',s)].decode()
secs={nm(s['n']):s for s in raw}

# dynamic symbols
dsym=secs['.dynsym']; dstr=secs['.dynstr']
def symname(i):
    o=dsym['off']+i*16
    nameoff=struct.unpack_from('<I',d,o)[0]
    s=dstr['off']+nameoff
    return d[s:d.index(b'\0',s)].decode()

# MIPS: .MIPS.stubs holds lazy-binding stubs; map stub addr -> symbol
stub_map={}
if '.MIPS.stubs' in secs:
    s=secs['.MIPS.stubs']
    md0=Cs(CS_ARCH_MIPS, CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
    cur=None
    for ins in md0.disasm(d[s['off']:s['off']+s['size']], s['addr']):
        # stubs look like: lw $25,%call16(sym)($gp); move $25,...; addiu $24, $zero, index
        if ins.mnemonic=='addiu' and '$t8' in ins.op_str or (ins.mnemonic=='addiu' and '$24' in ins.op_str):
            try:
                imm=int(ins.op_str.split(',')[-1].strip(),0)
                stub_map[cur]=symname(imm) if imm < dsym['size']//16 else f"idx{imm}"
            except: pass
        if ins.mnemonic=='lw' and cur is None: pass
        if ins.address % 16 == 0: cur=ins.address
print(f"resolved {len(stub_map)} PLT/stub entries")

t=secs['.text']
md=Cs(CS_ARCH_MIPS, CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
insns=list(md.disasm(d[t['off']:t['off']+t['size']], t['addr']))

print("\n=== ALL immediates equal to 5555 (0x15b3) anywhere in .text ===")
found=0
for i,ins in enumerate(insns):
    if ins.mnemonic in ('addiu','ori','li','lui','slti','sltiu'):
        for tok in ins.op_str.replace(',',' ').split():
            try: v=int(tok,0)
            except: continue
            if v==5555:
                found+=1
                print(f"  0x{ins.address:x}  {ins.mnemonic} {ins.op_str}")
                for j in range(max(0,i-4),min(len(insns),i+5)):
                    print(f"      0x{insns[j].address:08x} {insns[j].mnemonic:<8}{insns[j].op_str}")
print(f"  total: {found}")

print("\n=== other plausible port immediates near the fallback site (0x409100-0x409300) ===")
for ins in insns:
    if 0x409100 <= ins.address <= 0x409300 and ins.mnemonic in ('addiu','ori'):
        for tok in ins.op_str.replace(',',' ').split():
            try: v=int(tok,0)
            except: continue
            if 1 <= v <= 65535 and v not in (1,):
                print(f"  0x{ins.address:x} {ins.mnemonic} {ins.op_str}   (imm={v})")
                break
