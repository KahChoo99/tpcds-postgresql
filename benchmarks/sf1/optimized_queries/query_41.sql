
SELECT DISTINCT i1.i_product_name
FROM item i1
WHERE i1.i_manufact_id BETWEEN 934 AND 974
  AND EXISTS (
      SELECT 1
      FROM item i2
      WHERE i2.i_manufact = i1.i_manufact
        AND (
            (
                i2.i_category = 'Women'
                AND (
                    (i2.i_color IN ('royal', 'papaya')
                     AND i2.i_units IN ('Lb', 'Each')
                     AND i2.i_size IN ('medium', 'extra large'))
                    OR
                    (i2.i_color IN ('purple', 'pink')
                     AND i2.i_units IN ('Dozen', 'Ounce')
                     AND i2.i_size IN ('large', 'small'))
                    OR
                    (i2.i_color IN ('burlywood', 'goldenrod')
                     AND i2.i_units IN ('Carton', 'Oz')
                     AND i2.i_size IN ('medium', 'extra large'))
                    OR
                    (i2.i_color IN ('smoke', 'sandy')
                     AND i2.i_units IN ('Pound', 'Tbl')
                     AND i2.i_size IN ('large', 'small'))
                )
            )
            OR
            (
                i2.i_category = 'Men'
                AND (
                    (i2.i_color IN ('hot', 'dim')
                     AND i2.i_units IN ('Unknown', 'Case')
                     AND i2.i_size IN ('economy', 'petite'))
                    OR
                    (i2.i_color IN ('antique', 'drab')
                     AND i2.i_units IN ('Bundle', 'Gross')
                     AND i2.i_size IN ('medium', 'extra large'))
                    OR
                    (i2.i_color IN ('turquoise', 'black')
                     AND i2.i_units IN ('Gram', 'Bunch')
                     AND i2.i_size IN ('economy', 'petite'))
                    OR
                    (i2.i_color IN ('cornsilk', 'medium')
                     AND i2.i_units IN ('Ton', 'Pallet')
                     AND i2.i_size IN ('medium', 'extra large'))
                )
            )
        )
  )
ORDER BY i1.i_product_name
LIMIT 100;