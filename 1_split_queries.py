from pathlib import Path
import argparse


def split_queries(sql_text):
    """Split queries separated by 3 or more empty lines."""
    return [
        query.strip()
        for query in sql_text.split("\n\n\n\n")
        if query.strip()
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Split SQL queries separated by 3 empty lines."
    )

    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Input SQL file"
    )

    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Output directory"
    )

    args = parser.parse_args()

    input_file = Path(args.input)
    output_dir = Path(args.output)

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    sql_text = input_file.read_text(encoding="utf-8")

    queries = split_queries(sql_text)

    output_dir.mkdir(parents=True, exist_ok=True)

    for i, query in enumerate(queries, start=1):
        output_file = output_dir / f"query_{i}.sql"
        output_file.write_text(query + "\n", encoding="utf-8")

    print(f"Found {len(queries)} SQL queries.")
    print(f"Generated {len(queries)} files in: {output_dir}/")

    if len(queries) != 99:
        print(f"WARNING: Expected 99 queries, but found {len(queries)}.")


if __name__ == "__main__":
    main()