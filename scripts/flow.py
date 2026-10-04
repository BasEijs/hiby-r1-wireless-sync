import struct
from capstone import *
path="rootfs/usr/bin/adbd"; d=open(path,'rb').read()
e_shoff=struct.unpack_from('<I',d,0x20)[0]; e_shentsize=struct.unpack_from('<H',d,0x2E)[0]
e_shnum=struct.unpack_from('<H',d,0x30)[0]; e_shstrndx=struct.unpack_from('<H',d,0x32)[0]
def sh(i):
    o=e_shoff+i*e_shentsize
    n,t,f,a,off,sz,lnk,info,al,ent=struct.unpack_from('<IIIIIIIIII',d,o); return dict(n=n,typ=t,addr=a,off=off,size=sz)
raw=[sh(i) for i in range(e_shnum)]; st=raw[e_shstrndx]
def nm(x):
    s=st['off']+x; return d[s:d.index(b'\0',s)].decode()
secs={nm(s['n']):s for s in raw}
ro=secs['.rodata']
def getstr(va):
    if not (ro['addr']<=va<ro['addr']+ro['size']): return None
    o=ro['off']+(va-ro['addr'])
    e=d.index(b'\0',o)
    s=d[o:e]
    if 3<=len(s)<200 and all(32<=c<127 or c in (9,10) for c in s): return s.decode()
    return None
t=secs['.text']
md=Cs(CS_ARCH_MIPS, CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
ins=list(md.disasm(d[t['off']:t['off']+t['size']], t['addr']))
by={i.address:k for k,i in enumerate(ins)}

LO,HI=0x403d80,0x403ec0
pend={}
print(f"=== adbd .text 0x{LO:x}-0x{HI:x}  (annotated) ===")
for k,i in enumerate(ins):
    if not (LO<=i.address<=HI): continue
    ann=""
    if i.mnemonic=='lui':
        r,v=i.op_str.split(', '); pend[r.strip()]=int(v,0)<<16
    elif i.mnemonic=='addiu':
        p=[x.strip() for x in i.op_str.split(',')]
        if len(p)==3 and p[1] in pend:
            va=pend[p[1]]+struct.unpack('<h',struct.pack('<H',int(p[2],0)&0xffff))[0]
            s=getstr(va)
            if s: ann=f'   ; "{s}"'
            pend[p[0]]=va
    print(f"  0x{i.address:08x}  {i.mnemonic:<9}{i.op_str}{ann}")
