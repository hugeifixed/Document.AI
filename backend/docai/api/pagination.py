from rest_framework.filters import OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StableOrderingFilter(OrderingFilter):
    """Apply a unique tie-breaker so page boundaries cannot drift."""

    def get_ordering(self, request, queryset, view):
        ordering = list(super().get_ordering(request, queryset, view) or ())
        primary_key = queryset.model._meta.pk.name
        if primary_key not in {field.removeprefix("-") for field in ordering}:
            ordering.append(primary_key)
        return ordering


class StandardPagination(PageNumberPagination):
    """Predictable pagination metadata, configurable page size with a hard max."""

    page_size_query_param = "page_size"
    max_page_size = 200

    def get_paginated_response(self, data):
        page = self.page
        request = self.request
        if page is None or request is None:
            raise RuntimeError("paginate_queryset must run before get_paginated_response")
        return Response(
            {
                "count": page.paginator.count,
                "page": page.number,
                "page_size": self.get_page_size(request),
                "total_pages": page.paginator.num_pages,
                "results": data,
            }
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "page": {"type": "integer"},
                "page_size": {"type": "integer"},
                "total_pages": {"type": "integer"},
                "results": schema,
            },
        }


class RunItemPagination(StandardPagination):
    """Run review defaults to enough rows for useful progress inspection."""

    page_size = 50
