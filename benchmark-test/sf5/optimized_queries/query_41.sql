SELECT DISTINCT i1.i_product_name
FROM item i1
WHERE i1.i_manufact_id BETWEEN 987 AND 1027
  AND EXISTS (
      SELECT 1
      FROM item i2
      WHERE i2.i_manufact = i1.i_manufact
        AND (
            (
                i2.i_category = 'Women'
                AND (
                    (i2.i_color IN ('papaya', 'deep')
                     AND i2.i_units IN ('Pallet', 'Tsp')
                     AND i2.i_size IN ('economy', 'extra large'))
                    OR
                    (i2.i_color IN ('wheat', 'tan')
                     AND i2.i_units IN ('Gram', 'Dram')
                     AND i2.i_size IN ('medium', 'petite'))
                    OR
                    (i2.i_color IN ('lemon', 'chartreuse')
                     AND i2.i_units IN ('Case', 'Bundle')
                     AND i2.i_size IN ('economy', 'extra large'))
                    OR
                    (i2.i_color IN ('linen', 'ghost')
                     AND i2.i_units IN ('Ton', 'Box')
                     AND i2.i_size IN ('medium', 'petite'))
                )
            )
            OR
            (
                i2.i_category = 'Men'
                AND (
                    (i2.i_color IN ('pale', 'tomato')
                     AND i2.i_units IN ('Unknown', 'Cup')
                     AND i2.i_size IN ('small', 'N/A'))
                    OR
                    (i2.i_color IN ('forest', 'yellow')
                     AND i2.i_units IN ('N/A', 'Oz')
                     AND i2.i_size IN ('economy', 'extra large'))
                    OR
                    (i2.i_color IN ('seashell', 'metallic')
                     AND i2.i_units IN ('Each', 'Bunch')
                     AND i2.i_size IN ('small', 'N/A'))
                    OR
                    (i2.i_color IN ('floral', 'chiffon')
                     AND i2.i_units IN ('Lb', 'Gross')
                     AND i2.i_size IN ('economy', 'extra large'))
                )
            )
        )
  )
ORDER BY i1.i_product_name
LIMIT 100;