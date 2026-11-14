{#
    Fails for every combination of the given columns that appears on more than one row.
    ClickHouse groups NULL with NULL, so rows where a column is NULL are checked too: archive
    rows have no forecast version and still must be unique.
#}
{% test unique_combination_of_columns(model, combination_of_columns) %}
    {%- set columns = combination_of_columns | join(', ') %}
    select
        {{ columns }},
        count() as row_count
    from {{ model }}
    group by {{ columns }}
    having count() > 1
{% endtest %}
