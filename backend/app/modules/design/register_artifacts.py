import argparse
import json

from .execution_catalog import ExecutionCatalog, CatalogUnavailable


def main():
    parser=argparse.ArgumentParser(description='Register a pinned copied execution artifact snapshot')
    parser.add_argument('--directory',required=True)
    parser.add_argument('--source-id',required=True,choices=['arr-maas-cache','arr-design-executions'])
    args=parser.parse_args()
    try:
        print(json.dumps(ExecutionCatalog(args.directory).register(args.source_id)))
    except (CatalogUnavailable,ValueError,OSError):
        parser.exit(1,'Execution artifact registration failed\n')


if __name__=='__main__':main()
