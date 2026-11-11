from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Confirm that the API responds; real NASA data is not connected yet."""
    return Response({"status": "ok", "data_ready": False})


@api_view(["GET"])
@permission_classes([AllowAny])
def metadata(request):
    """Return available dates and a clearly labelled demo region."""
    from .demo_data import demo_metadata
    return Response(demo_metadata())


@api_view(["GET"])
@permission_classes([AllowAny])
def calendar_view(request):
    """Validate the requested period and return synthetic calendar values."""
    from .demo_data import demo_calendar
    from .serializers import CalendarQuerySerializer
    query = CalendarQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    return Response(demo_calendar())
