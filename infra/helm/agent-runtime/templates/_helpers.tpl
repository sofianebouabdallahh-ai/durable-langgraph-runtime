{{- define "nuria.fullname" -}}{{ .Release.Name }}{{- end }}

{{- define "nuria.labels" -}}
app.kubernetes.io/part-of: nuria
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.runtime.tag | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/* For pod templates, next to the selector labels (which carry the instance). */}}
{{- define "nuria.podLabels" -}}
app.kubernetes.io/part-of: nuria
app.kubernetes.io/version: {{ .Values.image.runtime.tag | quote }}
{{- end }}

{{- define "nuria.selector" -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/name: {{ .name }}
{{- end }}

{{/* Restricted Pod Security Standard (R10.10): every pod and container. */}}
{{- define "nuria.podSecurity" -}}
runAsNonRoot: true
seccompProfile: { type: RuntimeDefault }
{{- end }}
{{- define "nuria.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end }}

{{- define "nuria.runtimeImage" -}}{{ .Values.image.runtime.repository }}:{{ .Values.image.runtime.tag }}{{- end }}
{{- define "nuria.uiImage" -}}{{ .Values.image.ui.repository }}:{{ .Values.image.ui.tag }}{{- end }}

{{/* Kubernetes facts every runtime pod knows about itself (Downward API): the pod
     name is the worker's lease owner (R2.2) and a resource attribute on its spans. */}}
{{- define "nuria.downwardEnv" -}}
- name: POD_NAME
  valueFrom: { fieldRef: { fieldPath: metadata.name } }
- name: POD_NAMESPACE
  valueFrom: { fieldRef: { fieldPath: metadata.namespace } }
- name: NODE_NAME
  valueFrom: { fieldRef: { fieldPath: spec.nodeName } }
{{- end }}

{{/* Tracing and the UI's links, when monitoring is on. */}}
{{- define "nuria.monitoringEnv" -}}
{{- if .Values.monitoring.enabled }}
- { name: OTEL_EXPORTER_OTLP_ENDPOINT, value: "http://{{ include "nuria.fullname" . }}-otel-collector:4318" }
- { name: TRACE_UI_URL, value: {{ .Values.monitoring.traceUiUrl | quote }} }
- { name: DASHBOARD_URL, value: {{ .Values.monitoring.dashboardUrl | quote }} }
{{- end }}
{{- end }}

{{/* Spread a workload's pods across nodes (R10.11): best effort, so a drain with
     one node left still schedules them. */}}
{{- define "nuria.spread" -}}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels: {{- include "nuria.selector" . | nindent 8 }}
{{- end }}
