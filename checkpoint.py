"""Record or inspect verifiable local preparation checkpoints; never approves QA."""
import argparse
import json
from pathlib import Path
import team
from resilience import checkpoint, reusable


def runtime_scope(project):
    parts=team.snapshot(project)['scopes']
    return {'application':parts['application'],'environment':parts['environment']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['record','inspect'])
    parser.add_argument('name',choices=['prepare','build','browser','cleanup'])
    parser.add_argument('--artifact',action='append',default=[])
    parser.add_argument('--evidence',action='append',default=[])
    args=parser.parse_args();folder=team.PROJECT/'.supervisor/team-v2'
    scope=runtime_scope(team.PROJECT)
    if args.action=='record':
        result=checkpoint(folder,args.name,scope,args.artifact,args.evidence,team.save)
        print(json.dumps({'recorded':args.name,'scope':result['scope']}))
    else:
        record=team.load(folder/'checkpoints'/(args.name+'.json'),{})
        print(json.dumps({'name':args.name,'reusable':reusable(folder,record,scope),'checkpoint':record}))


if __name__=='__main__':main()
