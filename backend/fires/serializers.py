from rest_framework import serializers
from .demo_data import DEMO_MONTH, DEMO_REGION_ID, DEMO_YEAR


class CalendarQuerySerializer(serializers.Serializer):
    region_id = serializers.ChoiceField(choices=[DEMO_REGION_ID])
    year = serializers.IntegerField(min_value=1, max_value=9999)
    month = serializers.IntegerField(min_value=1, max_value=12)

    def validate(self, attrs):
        if (attrs["year"], attrs["month"]) != (DEMO_YEAR, DEMO_MONTH):
            raise serializers.ValidationError(
                "Сейчас доступен только тестовый календарь за август 2024 года."
            )
        return attrs
