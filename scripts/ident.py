import struct
from capstone import *
path="rootfs/usr/bin/adbd"; d=open(path,'rb').read()
e_shoff=struct.unpack_from('<I',d,0x20)[0]; e_shentsize=struct.unpack_from('<H',d,0x2E)[0]
e_shnum=struct.unpack_from('<H',d,0x30)[0]; e_shstrndx=struct.unpack_from('<H',d,0x32)[0]
def sh(i):
    o=e_shoff+i*e_shentsize
    n,t,f,a,off,sz,l,inf,al,ent=struct.unpack_from('<IIIIIIIIII',d,o); return dict(n=n,addr=a,off=off,size=sz)
raw=[sh(i) for i in range(e_shnum)]; st=raw[e_shstrndx]
def nm(x):
    s=st['off']+x; return d[s:d.index(b'\0',s)].decode()
secs={nm(s['n']):s for s in raw}; ro=secs['.rodata']; t=secs['.text']
def getstr(va):
    if not (ro['addr']<=va<ro['addr']+ro['size']): return None
    o=ro['off']+(va-ro['addr']); e=d.index(b'\0',o); s=d[o:e]
    if 2<=len(s)<220 and all(32<=c<127 or c in(9,10) for c in s): return s.decode()
md=Cs(CS_ARCH_MIPS, CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
ins=list(md.disasm(d[t['off']:t['off']+t['size']], t['addr']))

print("=== .rodata around 0x4166b0 ===")
o=ro['off']+(0x416680-ro['addr'])
print(repr(d[o:o+120]))

def dump(start,n,label):
    print(f"\n=== {label}: function at 0x{start:x} (first {n} insns, strings annotated) ===")
    pend={}; c=0
    for i in ins:
        if i.address<start: continue
        ann=""
        if i.mnemonic=='lui':
            r,v=i.op_str.split(', '); pend[r.strip()]=int(v,0)<<16
        elif i.mnemonic=='addiu':
            p=[x.strip() for x in i.op_str.split(',')]
            if len(p)==3 and p[1] in pend:
                va=pend[p[1]]+struct.unpack('<h',struct.pack('<H',int(p[2],0)&0xffff))[0]
                s=getstr(va)
                if s: ann=f'   ; "{s}"'
        print(f"  0x{i.address:08x}  {i.mnemonic:<9}{i.op_str}{ann}")
        c+=1
        if c>=n: break
dump(0x409a8c,34,"callee A (called with a0=5555)")
dump(0x413824,26,"callee B (the other branch)")
