{{/* Restricted Pod Security Standard: the same container hardening everywhere. */}}
{{- define "nuria-data.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end }}

{{- define "nuria-data.labels" -}}
app.kubernetes.io/part-of: nuria
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}
