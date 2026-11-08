select  distinct(i_product_name)
 from item i1
 where i_manufact_id between 864 and 864+40 
   and (select count(*) as item_cnt
        from item
        where (i_manufact = i1.i_manufact and
        ((i_category = 'Women' and 
        (i_color = 'cream' or i_color = 'smoke') and 
        (i_units = 'Case' or i_units = 'Bunch') and
        (i_size = 'economy' or i_size = 'small')
        ) or
        (i_category = 'Women' and
        (i_color = 'beige' or i_color = 'blanched') and
        (i_units = 'Carton' or i_units = 'Unknown') and
        (i_size = 'large' or i_size = 'petite')
        ) or
        (i_category = 'Men' and
        (i_color = 'tomato' or i_color = 'rose') and
        (i_units = 'Ounce' or i_units = 'Oz') and
        (i_size = 'extra large' or i_size = 'N/A')
        ) or
        (i_category = 'Men' and
        (i_color = 'frosted' or i_color = 'red') and
        (i_units = 'Dozen' or i_units = 'Dram') and
        (i_size = 'economy' or i_size = 'small')
        ))) or
       (i_manufact = i1.i_manufact and
        ((i_category = 'Women' and 
        (i_color = 'burlywood' or i_color = 'lavender') and 
        (i_units = 'Box' or i_units = 'Pallet') and
        (i_size = 'economy' or i_size = 'small')
        ) or
        (i_category = 'Women' and
        (i_color = 'lace' or i_color = 'floral') and
        (i_units = 'N/A' or i_units = 'Tsp') and
        (i_size = 'large' or i_size = 'petite')
        ) or
        (i_category = 'Men' and
        (i_color = 'peach' or i_color = 'navajo') and
        (i_units = 'Gram' or i_units = 'Pound') and
        (i_size = 'extra large' or i_size = 'N/A')
        ) or
        (i_category = 'Men' and
        (i_color = 'saddle' or i_color = 'deep') and
        (i_units = 'Tbl' or i_units = 'Each') and
        (i_size = 'economy' or i_size = 'small')
        )))) > 0
 order by i_product_name
 limit 100;
