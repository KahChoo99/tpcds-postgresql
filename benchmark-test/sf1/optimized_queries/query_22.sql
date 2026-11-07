with inventory_by_item as
    (select inv_item_sk
            ,sum(inv_quantity_on_hand) quantity_sum
            ,count(inv_quantity_on_hand) quantity_count
       from inventory
           ,date_dim
      where inv_date_sk=d_date_sk
        and d_month_seq between 1200 and 1200 + 11
      group by inv_item_sk)
select  i_product_name
             ,i_brand
             ,i_class
             ,i_category
             ,sum(quantity_sum) / nullif(sum(quantity_count),0) qoh
       from inventory_by_item
           ,item
       where inv_item_sk=i_item_sk
       group by rollup(i_product_name
                       ,i_brand
                       ,i_class
                       ,i_category)
order by qoh, i_product_name, i_brand, i_class, i_category
limit 100;
