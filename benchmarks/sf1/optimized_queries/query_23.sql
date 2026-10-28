with frequent_item_days as
 (select i_item_sk item_sk
  from store_sales
      ,date_dim
      ,item
  where ss_sold_date_sk = d_date_sk
    and ss_item_sk = i_item_sk
    and d_year in (1998,1998+1,1998+2,1998+3)
  group by i_item_sk,d_date
  having count(*) >4),
 frequent_ss_items as
 (select distinct item_sk
  from frequent_item_days),
 customer_store_sales as
 (select c_customer_sk
        ,sum(ss_quantity*ss_sales_price) all_store_sales
        ,sum(ss_quantity*ss_sales_price)
           filter (where d_year in (1998,1998+1,1998+2,1998+3)) four_year_store_sales
  from store_sales
      join customer on ss_customer_sk = c_customer_sk
      left join date_dim on ss_sold_date_sk = d_date_sk
  group by c_customer_sk),
 best_ss_customer as
 (select c_customer_sk
  from (select c_customer_sk
              ,all_store_sales
              ,max(four_year_store_sales) over () max_store_sales
        from customer_store_sales) customer_sales
  where all_store_sales > (95/100.0) * max_store_sales)
  select  sum(sales)
 from (select cs_quantity*cs_list_price sales
       from catalog_sales
           ,date_dim 
       where d_year = 1998 
         and d_moy = 2 
         and cs_sold_date_sk = d_date_sk 
         and cs_item_sk in (select item_sk from frequent_ss_items)
         and cs_bill_customer_sk in (select c_customer_sk from best_ss_customer)
      union all
      select ws_quantity*ws_list_price sales
       from web_sales 
           ,date_dim 
       where d_year = 1998 
         and d_moy = 2 
         and ws_sold_date_sk = d_date_sk 
         and ws_item_sk in (select item_sk from frequent_ss_items)
         and ws_bill_customer_sk in (select c_customer_sk from best_ss_customer)) 
 limit 100;
with frequent_item_days as
 (select i_item_sk item_sk
  from store_sales
      ,date_dim
      ,item
  where ss_sold_date_sk = d_date_sk
    and ss_item_sk = i_item_sk
    and d_year in (1998,1998 + 1,1998 + 2,1998 + 3)
  group by i_item_sk,d_date
  having count(*) >4),
 frequent_ss_items as
 (select distinct item_sk
  from frequent_item_days),
 customer_store_sales as
 (select c_customer_sk
        ,sum(ss_quantity*ss_sales_price) all_store_sales
        ,sum(ss_quantity*ss_sales_price)
           filter (where d_year in (1998,1998+1,1998+2,1998+3)) four_year_store_sales
  from store_sales
      join customer on ss_customer_sk = c_customer_sk
      left join date_dim on ss_sold_date_sk = d_date_sk
  group by c_customer_sk),
 best_ss_customer as
 (select c_customer_sk
  from (select c_customer_sk
              ,all_store_sales
              ,max(four_year_store_sales) over () max_store_sales
        from customer_store_sales) customer_sales
  where all_store_sales > (95/100.0) * max_store_sales)
  select  c_last_name,c_first_name,sales
 from (select c_last_name,c_first_name,sum(cs_quantity*cs_list_price) sales
        from catalog_sales
            ,customer
            ,date_dim 
        where d_year = 1998 
         and d_moy = 2 
         and cs_sold_date_sk = d_date_sk 
         and cs_item_sk in (select item_sk from frequent_ss_items)
         and cs_bill_customer_sk in (select c_customer_sk from best_ss_customer)
         and cs_bill_customer_sk = c_customer_sk 
       group by c_last_name,c_first_name
      union all
      select c_last_name,c_first_name,sum(ws_quantity*ws_list_price) sales
       from web_sales
           ,customer
           ,date_dim 
       where d_year = 1998 
         and d_moy = 2 
         and ws_sold_date_sk = d_date_sk 
         and ws_item_sk in (select item_sk from frequent_ss_items)
         and ws_bill_customer_sk in (select c_customer_sk from best_ss_customer)
         and ws_bill_customer_sk = c_customer_sk
       group by c_last_name,c_first_name) 
     order by c_last_name,c_first_name,sales
  limit 100;
