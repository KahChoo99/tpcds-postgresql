# tpcds-postgresql

## Phase 6: Query Generation

The TPC-DS queries are generated inside the `tpcds-tools` Docker container using our pre-configured PostgreSQL dialect template. 

**1. Access the tools container:**
```bash
docker exec -it tpcds-tools bash

```

**2. Navigate to the compiled tools directory:**

```bash
cd tools

```

**3. Generate the 99 TPC-DS business queries:**
example for the scale factor = 1 (can be change in this -scale 1)

```bash
./dsqgen -input ../query_templates/templates.lst -directory ../query_templates -dialect postgresql -scale 1 -output_dir /generated_queries

```

*(Note: If you see the message `Warning: This scale factor is valid for QUALIFICATION ONLY`, this is the expected successful behavior from TPC-DS, not an error).*

**4. Exit the container:**

```bash
exit

```

Once completed, the generated output file `query_0.sql` will automatically sync and be available in your local `./generated_queries` folder, ready for the validation phase.