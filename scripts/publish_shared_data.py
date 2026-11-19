"""Publish durable local deltas; never run full migrations on the shared store."""
import argparse
import json
import os
import sys
from dotenv import load_dotenv
from scraper.shared_publication import Publisher


def main():
    load_dotenv();os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('bootstrap','publish'))
    args=parser.parse_args();publisher=None
    try:
        publisher=Publisher(os.environ['DATABASE_URL'],os.environ['SHARED_DATABASE_URL'],
                            os.environ['ARCHIVE_DATABASE_ID'],os.environ['ARCHIVE_ROOT'])
        print(json.dumps(publisher.publish(bootstrap=args.phase=='bootstrap')))
        return 0
    except Exception as error:
        # libpq exceptions can contain connection parameters. Do not print them.
        print(json.dumps(dict(stage='PUBLICATION_STOPPED',error_type=type(error).__name__)),file=sys.stderr)
        return 1
    finally:
        if publisher:publisher.close()


if __name__=='__main__':raise SystemExit(main())
