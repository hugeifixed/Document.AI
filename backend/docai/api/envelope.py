"""Response contract:
  success: {"success": true, "message": "...", "data": {...}}
  error:   {"success": false, "message": "...", "errors": {...},
            "error_code": "...", "trace_id": "..."}
The renderer wraps every DRF response; the exception handler builds errors.
Views may set `response.message` to customize the success message."""

from rest_framework.renderers import JSONRenderer

from docai.logging.context import get_trace_id


class EnvelopeJSONRenderer(JSONRenderer):
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = (renderer_context or {}).get("response")
        # already an error envelope built by the exception handler
        if isinstance(data, dict) and data.get("success") is False and "error_code" in data:
            return super().render(data, accepted_media_type, renderer_context)
        if response is not None and response.exception:
            return super().render(data, accepted_media_type, renderer_context)
        message = getattr(response, "message", None) or "Operation completed successfully"
        payload = {
            "success": True,
            "message": message,
            "data": data if data is not None else {},
            "trace_id": get_trace_id(),
        }
        return super().render(payload, accepted_media_type, renderer_context)
