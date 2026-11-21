{#
    Use a folder's `+schema` as the ClickHouse database name exactly as written (silver, gold).
    dbt's default would build into `<target schema>_<+schema>`, e.g. `bronze_silver`.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
