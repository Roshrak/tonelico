#!/usr/bin/env python3
"""Post-install boot gate: retain protected entries and quarantine only rejected ones."""
import hashlib,json,os,re,shlex,stat,tempfile
from pathlib import Path

FALLBACK_PROFILE='/nix/var/nix/profiles/system-profiles/fallback'
REJECTED={
 130:'/nix/store/ndx0lwjaqrv1kkdkwmrmq3r0a16l0b1f-nixos-system-tonelico-nix-26.05.20260927.cf5e765',
 131:'/nix/store/4gjy25xrs8mxx141vksrkx3lri5ayxph-nixos-system-tonelico-nix-26.05.20260927.cf5e765',
}

def digest(p):
 return hashlib.sha256(p.read_bytes()).hexdigest()

def checked_path(p,uid,directory=False):
 s=p.lstat()
 if s.st_uid!=uid or stat.S_ISLNK(s.st_mode):raise RuntimeError('Unsafe owner/symlink: '+str(p))
 if directory and not stat.S_ISDIR(s.st_mode):raise RuntimeError('Directory required: '+str(p))
 if not directory and (not stat.S_ISREG(s.st_mode) or s.st_nlink!=1):raise RuntimeError('Single-link regular file required: '+str(p))
 return s

def fields(p):
 out={}
 for line in p.read_text().splitlines():
  if not line.strip() or line.lstrip().startswith('#'):continue
  k,*v=line.split(None,1)
  if k in out:raise RuntimeError('Duplicate boot-entry field: '+k)
  out[k]=v[0] if v else ''
 return out

def entry(p,top,uid):
 checked_path(p,uid)
 f=fields(p)
 args=shlex.split(f.get('options',''))
 inits=[x[5:] for x in args if x.startswith('init=')]
 if inits!=[top+'/init']:raise RuntimeError('Unexpected init lineage: '+str(p))
 return f

def sync_dir(p):
 fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:os.fsync(fd)
 finally:os.close(fd)

def protected_entries(profile=FALLBACK_PROFILE):
 m=re.fullmatch(r'fallback-([0-9]+)-link',os.readlink(profile))
 if not m:raise RuntimeError('Unexpected fallback profile link: '+profile)
 return {'nixos-fallback-generation-%s.conf'%m.group(1):os.path.realpath(profile)}

def quarantine(boot,protected=None,rejected=REJECTED,uid=0):
 if protected is None:protected=protected_entries()
 boot=Path(boot);checked_path(boot,uid,True)
 loader=boot/'loader';entries=loader/'entries'
 checked_path(loader,uid,True);checked_path(entries,uid,True)
 # Validate every fallback and payload before changing any rejected entry.
 for name,top in protected.items():
  f=entry(entries/name,top,uid)
  for key,resource in [('linux','kernel'),('initrd','initrd')]:
   value=Path(f.get(key,''))
   if not value.is_absolute() or '..' in value.parts:raise RuntimeError('Unsafe/missing boot payload path')
   payload=boot/value.relative_to('/')
   checked_path(payload,uid)
   if digest(payload)!=digest(Path(top)/resource):raise RuntimeError('Recovery payload mismatch: '+str(payload))
  if not (Path(top)/'init').is_file():raise RuntimeError('Recovery init missing')
 archive=loader/'rejected-generation-evidence'
 if archive.exists() or archive.is_symlink():checked_path(archive,uid,True)
 else:archive.mkdir(mode=0o700)
 planned=[]
 for n,top in rejected.items():
  p=entries/('nixos-generation-%s.conf'%n)
  if not p.exists() and not p.is_symlink():continue
  entry(p,top,uid)
  h=digest(p);target=archive/('generation-%s-%s.conf.rejected'%(n,h))
  if target.exists() or target.is_symlink():
   checked_path(target,uid)
   if digest(target)!=h:raise RuntimeError('Quarantine evidence mismatch')
   # Duplicate verified generated entry; retain both files rather than delete.
   target=archive/('generation-%s-%s-%s.conf.rejected'%(n,h,os.urandom(8).hex()))
  planned.append((n,p,target,h))
 # No rejected entry moves until every source and archive target is validated.
 moves=[]
 for n,p,target,h in planned:
  if digest(p)!=h:raise RuntimeError('Rejected entry changed after preflight')
  p.rename(target)
  if digest(target)!=h:raise RuntimeError('Quarantine rename verification failed')
  sync_dir(archive);sync_dir(entries)
  moves.append({'generation':n,'source':str(p),'archive':str(target),'sha256':h})
 sync_dir(loader);sync_dir(boot)
 return moves

if __name__=='__main__':
 if os.geteuid()!=0:raise SystemExit('Root boot installer required')
 print(json.dumps({'rejected_boot_entries_quarantined':quarantine('/boot')}))
