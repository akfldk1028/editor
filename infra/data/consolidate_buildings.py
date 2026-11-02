"""Copy physical legacy assets to external storage, preserving and hashing originals."""
import argparse,hashlib,json,os,shutil,time
from pathlib import Path

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def physical_files(root):
    pending=[root]
    while pending:
        current=pending.pop()
        with os.scandir(current) as entries:items=list(entries)
        for entry in items:
            if entry.is_symlink() or entry.is_junction():continue
            if entry.is_dir(follow_symlinks=False):pending.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):yield Path(entry.path)

def consolidate(source,destination,receipt):
    source=source.resolve();destination=destination.resolve()
    if source==destination or destination.is_relative_to(source):raise ValueError('Destination must be outside the source')
    destination.mkdir(parents=True,exist_ok=True);receipt.parent.mkdir(parents=True,exist_ok=True)
    count=0;total=0
    with receipt.open('a',encoding='utf-8') as log:
        for file in physical_files(source):
            relative=file.relative_to(source);target=destination/relative
            # Catalog and status files remain owned by their publisher. Copy only
            # immutable region directories; the release pointer is already external.
            if len(relative.parts)<2:continue
            if not target.resolve().is_relative_to(destination):raise ValueError('Destination escapes data root')
            before=file.stat();checksum=digest(file)
            if target.exists():
                if target.stat().st_size!=before.st_size or digest(target)!=checksum:raise ValueError(f'Conflicting immutable asset: {relative}')
                state='already_verified'
            else:
                target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_name(target.name+f'.copying-{os.getpid()}')
                shutil.copyfile(file,temp)
                if temp.stat().st_size!=before.st_size or digest(temp)!=checksum:raise ValueError(f'Copy verification failed: {relative}')
                after=file.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Source changed during copy')
                if target.exists():raise ValueError('Concurrent destination publication')
                temp.rename(target);state='copied_verified'
            log.write(json.dumps({'key':relative.as_posix(),'bytes':before.st_size,'sha256':checksum,'state':state})+'\n')
            count+=1;total+=before.st_size
            if count%500==0:log.flush();print(json.dumps({'files':count,'bytes':total}),flush=True)
    return {'files':count,'bytes':total,'originalsDeleted':0}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--destination',type=Path,required=True);p.add_argument('--receipt',type=Path,required=True);a=p.parse_args()
    print(json.dumps(consolidate(a.source,a.destination,a.receipt)))
