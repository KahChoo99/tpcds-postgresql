SELECT DISTINCT i1.i_product_name
FROM item i1
WHERE i1.i_manufact_id BETWEEN 864 AND 904
  AND EXISTS (
      SELECT 1
      FROM item i2
      WHERE i2.i_manufact = i1.i_manufact
        AND (
            (
                i2.i_category = 'Women'
                AND (
                    (i2.i_color IN ('cream', 'smoke')
                     AND i2.i_units IN ('Case', 'Bunch')
                     AND i2.i_size IN ('economy', 'small'))
                    OR
                    (i2.i_color IN ('beige', 'blanched')
                     AND i2.i_units IN ('Carton', 'Unknown')
                     AND i2.i_size IN ('large', 'petite'))
                    OR
                    (i2.i_color IN ('burlywood', 'lavender')
                     AND i2.i_units IN ('Box', 'Pallet')
                     AND i2.i_size IN ('economy', 'small'))
                    OR
                    (i2.i_color IN ('lace', 'floral')
                     AND i2.i_units IN ('N/A', 'Tsp')
                     AND i2.i_size IN ('large', 'petite'))
                )
            )
            OR
            (
                i2.i_category = 'Men'
                AND (
                    (i2.i_color IN ('tomato', 'rose')
                     AND i2.i_units IN ('Ounce', 'Oz')
                     AND i2.i_size IN ('extra large', 'N/A'))
                    OR
                    (i2.i_color IN ('frosted', 'red')
                     AND i2.i_units IN ('Dozen', 'Dram')
                     AND i2.i_size IN ('economy', 'small'))
                    OR
                    (i2.i_color IN ('peach', 'navajo')
                     AND i2.i_units IN ('Gram', 'Pound')
                     AND i2.i_size IN ('extra large', 'N/A'))
                    OR
                    (i2.i_color IN ('saddle', 'deep')
                     AND i2.i_units IN ('Tbl', 'Each')
                     AND i2.i_size IN ('economy', 'small'))
                )
            )
        )
  )
ORDER BY i1.i_product_name
LIMIT 100;