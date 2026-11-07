select  distinct(i_product_name)
 from item i1
 where i_manufact_id between 827 and 827+40 
   and (select count(*) as item_cnt
        from item
        where (i_manufact = i1.i_manufact and
        ((i_category = 'Women' and 
        (i_color = 'tan' or i_color = 'lemon') and 
        (i_units = 'Tbl' or i_units = 'Pallet') and
        (i_size = 'N/A' or i_size = 'large')
        ) or
        (i_category = 'Women' and
        (i_color = 'ghost' or i_color = 'purple') and
        (i_units = 'Pound' or i_units = 'Gross') and
        (i_size = 'economy' or i_size = 'extra large')
        ) or
        (i_category = 'Men' and
        (i_color = 'turquoise' or i_color = 'dark') and
        (i_units = 'Tsp' or i_units = 'Each') and
        (i_size = 'small' or i_size = 'petite')
        ) or
        (i_category = 'Men' and
        (i_color = 'yellow' or i_color = 'pink') and
        (i_units = 'Bunch' or i_units = 'Gram') and
        (i_size = 'N/A' or i_size = 'large')
        ))) or
       (i_manufact = i1.i_manufact and
        ((i_category = 'Women' and 
        (i_color = 'peach' or i_color = 'dim') and 
        (i_units = 'Ounce' or i_units = 'Dram') and
        (i_size = 'N/A' or i_size = 'large')
        ) or
        (i_category = 'Women' and
        (i_color = 'smoke' or i_color = 'lime') and
        (i_units = 'N/A' or i_units = 'Case') and
        (i_size = 'economy' or i_size = 'extra large')
        ) or
        (i_category = 'Men' and
        (i_color = 'spring' or i_color = 'cream') and
        (i_units = 'Dozen' or i_units = 'Carton') and
        (i_size = 'small' or i_size = 'petite')
        ) or
        (i_category = 'Men' and
        (i_color = 'orange' or i_color = 'brown') and
        (i_units = 'Box' or i_units = 'Bundle') and
        (i_size = 'N/A' or i_size = 'large')
        )))) > 0
 order by i_product_name
 limit 100;
