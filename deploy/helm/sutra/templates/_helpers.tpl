{{/* Names and labels shared by every object. */}}
{{- define "sutra.fullname" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sutra.labels" -}}
app.kubernetes.io/name: sutra
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: sutra
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
sutra.io/env: {{ .Values.global.env }}
{{- end -}}

{{- define "sutra.selector" -}}
app.kubernetes.io/name: sutra
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* The same selector as inline JSON, for use inside flow mappings ({ matchLabels: … }). */}}
{{- define "sutra.selectorJson" -}}
{{- include "sutra.selector" . | fromYaml | toJson -}}
{{- end -}}

{{/* image: registry/repository@digest, else :tag, else :appVersion. Digests make deploys immutable. */}}
{{- define "sutra.image" -}}
{{- $img := index .root.Values.image .name -}}
{{- $reg := .root.Values.global.imageRegistry -}}
{{- $repo := ternary (printf "%s/%s" $reg $img.repository) $img.repository (ne $reg "") -}}
{{- if $img.digest -}}{{ $repo }}@{{ $img.digest }}{{- else -}}{{ $repo }}:{{ default .root.Chart.AppVersion $img.tag }}{{- end -}}
{{- end -}}

{{- define "sutra.secretName" -}}
{{- default (printf "%s-secrets" (include "sutra.fullname" .)) .Values.existingSecret -}}
{{- end -}}

{{/* Hardened container defaults: non-root, read-only root fs, no capabilities, RuntimeDefault seccomp. */}}
{{- define "sutra.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
runAsNonRoot: true
capabilities: { drop: ["ALL"] }
seccompProfile: { type: RuntimeDefault }
{{- end -}}

{{- define "sutra.podSecurity" -}}
runAsNonRoot: true
runAsUser: {{ .Values.podSecurity.runAsUser }}
runAsGroup: {{ .Values.podSecurity.runAsUser }}
fsGroup: {{ .Values.podSecurity.fsGroup }}
seccompProfile: { type: RuntimeDefault }
{{- end -}}

{{- define "sutra.spread" -}}
{{- if .root.Values.topologySpread }}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector: { matchLabels: {{ include "sutra.selectorJson" . }} }
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector: { matchLabels: {{ include "sutra.selectorJson" . }} }
{{- end }}
{{- end -}}

{{/* Environment for every API-image container (API and jobs). */}}
{{- define "sutra.apiEnv" -}}
envFrom:
  - configMapRef: { name: {{ include "sutra.fullname" . }}-config }
env:
  - { name: SUTRA_DATABASE_URL, valueFrom: { secretKeyRef: { name: {{ include "sutra.secretName" . }}, key: database_url } } }
  - { name: SUTRA_JWT_SECRET, valueFrom: { secretKeyRef: { name: {{ include "sutra.secretName" . }}, key: jwt_secret } } }
  - { name: SUTRA_PII_HMAC_KEY, valueFrom: { secretKeyRef: { name: {{ include "sutra.secretName" . }}, key: pii_hmac_key } } }
  - { name: SUTRA_RATE_LIMIT_STORAGE_URI, valueFrom: { secretKeyRef: { name: {{ include "sutra.secretName" . }}, key: rate_limit_storage_uri } } }
  - { name: ANTHROPIC_API_KEY, valueFrom: { secretKeyRef: { name: {{ include "sutra.secretName" . }}, key: anthropic_api_key, optional: true } } }
{{- end -}}
