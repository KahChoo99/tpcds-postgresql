select  distinct(i_product_name)
 from item i1
 where i_manufact_id between 987 and 987+40 
   and (select count(*) as item_cnt
        from item
        where (i_manufact = i1.i_manufact and
        ((i_category = 'Women' and 
        (i_color = 'papaya' or i_color = 'deep') and 
        (i_units = 'Pallet' or i_units = 'Tsp') and
        (i_size = 'economy' or i_size = 'extra large')
        ) or
        (i_category = 'Women' and
        (i_color = 'wheat' or i_color = 'tan') and
        (i_units = 'Gram' or i_units = 'Dram') and
        (i_size = 'medium' or i_size = 'petite')
        ) or
        (i_category = 'Men' and
        (i_color = 'pale' or i_color = 'tomato') and
        (i_units = 'Unknown' or i_units = 'Cup') and
        (i_size = 'small' or i_size = 'N/A')
        ) or
        (i_category = 'Men' and
        (i_color = 'forest' or i_color = 'yellow') and
        (i_units = 'N/A' or i_units = 'Oz') and
        (i_size = 'economy' or i_size = 'extra large')
        ))) or
       (i_manufact = i1.i_manufact and
        ((i_category = 'Women' and 
        (i_color = 'lemon' or i_color = 'chartreuse') and 
        (i_units = 'Case' or i_units = 'Bundle') and
        (i_size = 'economy' or i_size = 'extra large')
        ) or
        (i_category = 'Women' and
        (i_color = 'linen' or i_color = 'ghost') and
        (i_units = 'Ton' or i_units = 'Box') and
        (i_size = 'medium' or i_size = 'petite')
        ) or
        (i_category = 'Men' and
        (i_color = 'seashell' or i_color = 'metallic') and
        (i_units = 'Each' or i_units = 'Bunch') and
        (i_size = 'small' or i_size = 'N/A')
        ) or
        (i_category = 'Men' and
        (i_color = 'floral' or i_color = 'chiffon') and
        (i_units = 'Lb' or i_units = 'Gross') and
        (i_size = 'economy' or i_size = 'extra large')
        )))) > 0
 order by i_product_name
 limit 100;
