"""Usage: python -m fluid_core input.csv output.csv"""
import argparse
from .batch import run_csv

def main():
    parser=argparse.ArgumentParser(description='Research prototype for fluid-inclusion calculations')
    parser.add_argument('input_csv'); parser.add_argument('output_csv')
    args=parser.parse_args()
    total,ok=run_csv(args.input_csv,args.output_csv)
    print(f'Processed {total} entries, ok={ok}, errors={total-ok}; saved {args.output_csv}')

if __name__=='__main__':main()
