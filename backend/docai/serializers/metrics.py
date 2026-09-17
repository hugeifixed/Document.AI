"""Strict query and public response contracts for workspace metrics."""

from datetime import UTC, timedelta

from django.utils import timezone
from rest_framework import serializers


class MetricsScopeSerializer(serializers.Serializer):
    project = serializers.UUIDField(required=False)
    dataset = serializers.UUIDField(required=False)
    range = serializers.ChoiceField(choices=["today", "7d", "30d", "90d", "custom"], default="30d")
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)

    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(dict.fromkeys(sorted(unknown), "Unknown filter."))
        if hasattr(data, "getlist"):
            repeated = [key for key in data if len(data.getlist(key)) > 1]
            if repeated:
                raise serializers.ValidationError(dict.fromkeys(repeated, "Supply only once."))
        return super().to_internal_value({key: value for key, value in data.items() if value != ""})

    def validate(self, attrs):
        today = timezone.now().astimezone(UTC).date()
        if attrs["range"] == "custom":
            if "start" not in attrs or "end" not in attrs:
                raise serializers.ValidationError("Custom range requires start and end dates.")
            start, end = attrs["start"], attrs["end"]
            if start > end or end > today or (end - start).days >= 90:
                raise serializers.ValidationError(
                    "Dates must be ordered, not future, and at most 90 inclusive days."
                )
        else:
            if "start" in attrs or "end" in attrs:
                raise serializers.ValidationError(
                    "Start and end are only accepted for a custom range."
                )
            days = {"today": 1, "7d": 7, "30d": 30, "90d": 90}[attrs["range"]]
            attrs["start"], attrs["end"] = today - timedelta(days=days - 1), today
        return attrs


class MetricsQuerySerializer(MetricsScopeSerializer):
    document_type = serializers.CharField(required=False, max_length=64)
    status = serializers.ChoiceField(required=False, choices=["succeeded", "failed"])


class UsageQuerySerializer(MetricsScopeSerializer):
    provider = serializers.CharField(required=False, max_length=32)
    deployment = serializers.CharField(required=False, max_length=120)
    stage = serializers.CharField(required=False, max_length=32)


class MetricsMetaSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    timezone = serializers.CharField()
    as_of = serializers.DateTimeField()
    cache_ttl_seconds = serializers.IntegerField()
    applied_filters = serializers.DictField()


class DurationSerializer(serializers.Serializer):
    completed_jobs = serializers.IntegerField()
    duration_sample_count = serializers.IntegerField()
    median_duration_ms = serializers.FloatField(allow_null=True)
    p95_duration_ms = serializers.FloatField(allow_null=True)


class ProcessingDaySerializer(DurationSerializer):
    date = serializers.DateField()
    succeeded = serializers.IntegerField()
    failed = serializers.IntegerField()


class TypeOptionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]


class TypeCountSerializer(TypeOptionSerializer):
    executions = serializers.IntegerField()


class PhaseCountSerializer(TypeOptionSerializer):
    count = serializers.IntegerField()


class ProcessingSerializer(DurationSerializer):
    daily = ProcessingDaySerializer(many=True)
    by_document_type = TypeCountSerializer(many=True)
    failures_by_phase = PhaseCountSerializer(many=True)
    document_type_options = TypeOptionSerializer(many=True)


class RunDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    succeeded = serializers.IntegerField()
    failed = serializers.IntegerField()
    partial = serializers.IntegerField()  # type: ignore[assignment]
    cancelled = serializers.IntegerField()


class RunMetricsSerializer(serializers.Serializer):
    succeeded = serializers.IntegerField()
    failed = serializers.IntegerField()
    partial = serializers.IntegerField()  # type: ignore[assignment]
    cancelled = serializers.IntegerField()
    success_rate = serializers.FloatField(allow_null=True)
    daily = RunDaySerializer(many=True)


class ReviewDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    field_decisions = serializers.IntegerField()
    classification_decisions = serializers.IntegerField()


class ReviewMetricsSerializer(serializers.Serializer):
    backlog_fields = serializers.IntegerField()
    backlog_classifications = serializers.IntegerField()
    backlog_segments = serializers.IntegerField()
    backlog_documents = serializers.IntegerField()
    decision_count = serializers.IntegerField()
    field_decision_count = serializers.IntegerField()
    field_correction_count = serializers.IntegerField()
    field_correction_rate = serializers.FloatField(allow_null=True)
    daily = ReviewDaySerializer(many=True)


class MetricsResponseSerializer(serializers.Serializer):
    meta = MetricsMetaSerializer()
    processing = ProcessingSerializer()
    runs = RunMetricsSerializer()
    review = ReviewMetricsSerializer()


class UsageTotalsSerializer(serializers.Serializer):
    calls = serializers.IntegerField()
    measured_calls = serializers.IntegerField()
    total_tokens = serializers.IntegerField(allow_null=True)


class UsageDaySerializer(UsageTotalsSerializer):
    date = serializers.DateField()


class UsageOptionsSerializer(serializers.Serializer):
    providers = serializers.ListField(child=serializers.CharField())
    deployments = serializers.ListField(child=serializers.CharField())
    stages = serializers.ListField(child=serializers.CharField())


class UsageMetricsResponseSerializer(UsageTotalsSerializer):
    meta = MetricsMetaSerializer()
    daily = UsageDaySerializer(many=True)
    filter_options = UsageOptionsSerializer()
