SELECT DISTINCT i1.i_product_name
FROM item i1
WHERE i1.i_manufact_id BETWEEN 827 AND 867
  AND EXISTS (
      SELECT 1
      FROM item i2
      WHERE i2.i_manufact = i1.i_manufact
        AND (
            (
                i2.i_category = 'Women'
                AND (
                    (i2.i_color IN ('tan', 'lemon')
                     AND i2.i_units IN ('Tbl', 'Pallet')
                     AND i2.i_size IN ('N/A', 'large'))
                    OR
                    (i2.i_color IN ('ghost', 'purple')
                     AND i2.i_units IN ('Pound', 'Gross')
                     AND i2.i_size IN ('economy', 'extra large'))
                    OR
                    (i2.i_color IN ('peach', 'dim')
                     AND i2.i_units IN ('Ounce', 'Dram')
                     AND i2.i_size IN ('N/A', 'large'))
                    OR
                    (i2.i_color IN ('smoke', 'lime')
                     AND i2.i_units IN ('N/A', 'Case')
                     AND i2.i_size IN ('economy', 'extra large'))
                )
            )
            OR
            (
                i2.i_category = 'Men'
                AND (
                    (i2.i_color IN ('turquoise', 'dark')
                     AND i2.i_units IN ('Tsp', 'Each')
                     AND i2.i_size IN ('small', 'petite'))
                    OR
                    (i2.i_color IN ('yellow', 'pink')
                     AND i2.i_units IN ('Bunch', 'Gram')
                     AND i2.i_size IN ('N/A', 'large'))
                    OR
                    (i2.i_color IN ('spring', 'cream')
                     AND i2.i_units IN ('Dozen', 'Carton')
                     AND i2.i_size IN ('small', 'petite'))
                    OR
                    (i2.i_color IN ('orange', 'brown')
                     AND i2.i_units IN ('Box', 'Bundle')
                     AND i2.i_size IN ('N/A', 'large'))
                )
            )
        )
  )
ORDER BY i1.i_product_name
LIMIT 100;