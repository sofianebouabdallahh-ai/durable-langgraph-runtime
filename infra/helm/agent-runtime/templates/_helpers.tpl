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

{{- define "nuria.sandboxImage" -}}{{ .Values.sandbox.image.repository }}:{{ .Values.sandbox.image.tag }}{{- end }}

{{/* Where the runtime finds the tools' services (L6), next to the ConfigMap's settings. */}}
{{- define "nuria.toolsConfig" -}}
{{- $name := include "nuria.fullname" . }}
SEARXNG_URL: {{ if .Values.search.enabled }}{{ printf "http://%s-searxng:8080" $name | quote }}{{ else }}""{{ end }}
FETCHER_URL: {{ if .Values.fetcher.enabled }}{{ printf "http://%s-fetcher:8090" $name | quote }}{{ else }}""{{ end }}
SANDBOXD_URL: {{ if .Values.sandbox.enabled }}{{ printf "http://%s-sandboxd:8070" $name | quote }}{{ else }}""{{ end }}
{{- end }}

{{/* Redis (H10): the ConfigMap's REDIS_URL with the Secret's password put in. An explicit
     env entry, which wins over envFrom; the kubelet expands $(REDIS_PASSWORD) in it. */}}
{{- define "nuria.redisEnv" -}}
{{- if .Values.redis.passwordKey }}
{{- $url := required "config.REDIS_URL is needed" .Values.config.REDIS_URL }}
{{- if contains "@" $url }}{{ fail "config.REDIS_URL must carry no credential: the password is redis.passwordKey in the Secret" }}{{ end }}
{{- $parts := splitn "://" 2 $url }}
- name: REDIS_PASSWORD
  valueFrom: { secretKeyRef: { name: {{ .Values.secretName }}, key: {{ .Values.redis.passwordKey }} } }
- { name: REDIS_URL, value: {{ printf "%s://:$(REDIS_PASSWORD)@%s" $parts._0 $parts._1 | quote }} }
{{- end }}
{{- end }}

{{/* Public addresses only (NetworkPolicy `to`): not the cluster, not private networks,
     not link-local (cloud metadata), not loopback or carrier-grade NAT. */}}
{{- define "nuria.publicInternet" -}}
- ipBlock:
    cidr: 0.0.0.0/0
    except: [0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16]
- ipBlock:
    cidr: ::/0
    except: ["::1/128", "fc00::/7", "fe80::/10"]
{{- end }}

{{/* Nuria's own Service names, short and full (H3: outbound requests never go there). */}}
{{/* The names a browser may use for Nuria (H3): the ingress host and ui.hostnames. */}}
{{- define "nuria.uiHostnames" -}}
{{- $names := .Values.ui.hostnames | default list -}}
{{- if .Values.ingress.host -}}{{- $names = prepend $names .Values.ingress.host -}}{{- end -}}
{{- join " " $names -}}
{{- end -}}

{{- define "nuria.internalHosts" -}}
{{- $f := include "nuria.fullname" . -}}
{{- $ns := .Release.Namespace -}}
{{- $names := list -}}
{{- range list "api" "api-pods" "ui" "fetcher" "sandboxd" "searxng" -}}
{{- $names = append $names (printf "%s-%s" $f .) -}}
{{- $names = append $names (printf "%s-%s.%s.svc.cluster.local" $f . $ns) -}}
{{- end -}}
{{- $names = concat $names (list "postgres" "redis" (printf "postgres.%s.svc.cluster.local" $ns) (printf "redis.%s.svc.cluster.local" $ns) "kubernetes.default.svc" "kubernetes.default.svc.cluster.local") -}}
{{- join " " $names -}}
{{- end -}}
