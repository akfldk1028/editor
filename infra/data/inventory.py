"""Read-only data inventory; directory links are reported rather than followed."""
import argparse,json,os,time
from pathlib import Path

def inventory(label,path):
    root=Path(path);row={'label':label,'path':str(root),'resolvedPath':str(root.resolve()),'exists':root.exists(),'files':0,'bytes':0,'directories':0,'linksSkipped':0,'errors':0}
    if not root.exists():return row
    if root.is_file():row.update(files=1,bytes=root.stat().st_size);return row
    stack=[str(root)]
    while stack:
        folder=stack.pop();row['directories']+=1
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink() or (hasattr(entry,'is_junction') and entry.is_junction()):row['linksSkipped']+=1;continue
                        if entry.is_dir(follow_symlinks=False):stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):row['files']+=1;row['bytes']+=entry.stat(follow_symlinks=False).st_size
                    except OSError:row['errors']+=1
        except OSError:row['errors']+=1
    return row

def main():
    p=argparse.ArgumentParser();p.add_argument('--entry',action='append',required=True,help='label=path');p.add_argument('--output',type=Path,required=True);a=p.parse_args();rows=[]
    for entry in a.entry:
        label,path=entry.split('=',1);row=inventory(label,path);rows.append(row)
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'checkedAt':time.time(),'rows':rows},indent=2),encoding='utf-8')
        print(json.dumps(row),flush=True)

if __name__=='__main__':main()
