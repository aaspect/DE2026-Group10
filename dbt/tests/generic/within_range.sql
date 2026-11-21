{#
    Fails for every non-null value below `min_value` or above `max_value`. Both limits are
    inclusive and optional; NULL always passes.
#}
{% test within_range(model, column_name, min_value=none, max_value=none) %}
    select {{ column_name }}
    from {{ model }}
    where {{ column_name }} is not null
      and (
        false
        {%- if min_value is not none %} or {{ column_name }} < {{ min_value }}{% endif %}
        {%- if max_value is not none %} or {{ column_name }} > {{ max_value }}{% endif %}
      )
{% endtest %}
