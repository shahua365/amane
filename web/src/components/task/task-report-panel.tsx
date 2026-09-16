import { Alert, Badge, Group, Stack, Text, ThemeIcon } from "@mantine/core";
import {
  IconAlertCircle,
  IconCheck,
  IconDatabase,
  IconExternalLink,
  IconUser,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { getTaskReportOptions } from "@/client/@tanstack/react-query.gen";
import type { SiteOutcomeKind, SiteOutcomeRecord, TaskType } from "@/client/types.gen";
import { assertNever } from "@/lib/exhaustive";
import { SITE_OUTCOME_KINDS } from "@/lib/exhaustive-maps";

interface TaskReportPanelProps {
  taskId: number;
  failed: boolean;
  taskType?: TaskType;
}

export function TaskReportPanel({ taskId, failed, taskType }: TaskReportPanelProps) {
  const { t } = useTranslation("tasks");
  const { data, isLoading, isError } = useQuery({
    ...getTaskReportOptions({ path: { task_id: taskId } }),
  });

  if (isLoading) {
    return (
      <Text size="xs" c="dimmed">
        {t("report.loading")}
      </Text>
    );
  }

  if (isError || data == null) {
    return (
      <Text size="xs" c="dimmed">
        {t("report.unavailable")}
      </Text>
    );
  }

  const showSiteOutcomes = taskType === "scrape" || taskType === "actor_scrape";
  const outcomes = showSiteOutcomes ? (data.outcomes ?? []) : [];
  const headline = data.headline;
  const metadataId = taskType === "scrape" ? data.metadata_id : undefined;
  const actorId = taskType === "actor_scrape" ? data.actor_id : undefined;
  const groups = groupByOutcome(outcomes);
  const empty =
    !failed && !headline && metadataId == null && actorId == null && outcomes.length === 0;

  return (
    <Stack gap="md">
      {failed && headline ? (
        <Alert
          color="red"
          variant="light"
          icon={<IconAlertCircle size={16} />}
          title={t("report.headline")}
        >
          <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
            {headline}
          </Text>
        </Alert>
      ) : null}

      {!failed && headline ? (
        <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
          {headline}
        </Text>
      ) : null}

      {metadataId != null ? (
        <Group gap="sm" wrap="nowrap">
          <ThemeIcon size="md" radius="md" variant="light" color="teal">
            <IconExternalLink size={14} />
          </ThemeIcon>
          <div style={{ minWidth: 0 }}>
            <Text size="xs" c="dimmed" lh={1.3}>
              {t("report.metadata")}
            </Text>
            <Link
              to="/meta/$metadataId"
              params={{ metadataId: String(metadataId) }}
              style={{ textDecoration: "none" }}
            >
              <Text component="span" size="sm" fw={600} c="var(--mantine-color-anchor)">
                {t("report.viewMetadata", { id: metadataId })}
              </Text>
            </Link>
          </div>
        </Group>
      ) : null}

      {actorId != null ? (
        <Group gap="sm" wrap="nowrap">
          <ThemeIcon size="md" radius="md" variant="light" color="teal">
            <IconUser size={14} />
          </ThemeIcon>
          <div style={{ minWidth: 0 }}>
            <Text size="xs" c="dimmed" lh={1.3}>
              {t("report.actor")}
            </Text>
            <Link
              to="/actors/$actorId"
              params={{ actorId: String(actorId) }}
              style={{ textDecoration: "none" }}
            >
              <Text component="span" size="sm" fw={600} c="var(--mantine-color-anchor)">
                {t("report.viewActor", { id: actorId })}
              </Text>
            </Link>
          </div>
        </Group>
      ) : null}

      {empty ? (
        <Text size="sm" c="dimmed">
          {t("report.successEmpty")}
        </Text>
      ) : null}

      {groups.map(({ kind, rows }) => (
        <OutcomeGroup key={kind} kind={kind} rows={rows} />
      ))}
    </Stack>
  );
}

function OutcomeGroup({ kind, rows }: { kind: SiteOutcomeKind; rows: SiteOutcomeRecord[] }) {
  const { t } = useTranslation("tasks");
  const color = outcomeColor(kind);

  return (
    <Stack gap={6}>
      <Group gap={6} wrap="nowrap">
        <ThemeIcon size={22} radius="sm" variant="light" color={color}>
          {outcomeIcon(kind)}
        </ThemeIcon>
        <Text size="sm" fw={600}>
          {t(`report.group.${kind}`)}
        </Text>
        <Text size="xs" c="dimmed">
          {rows.length}
        </Text>
      </Group>

      {kind === "failed" || kind === "blocked" ? (
        <Stack gap={4}>
          {rows.map((row) => (
            <FailedSiteRow key={row.site} row={row} />
          ))}
        </Stack>
      ) : (
        <Group gap={6}>
          {rows.map((row) => (
            <Badge key={row.site} size="sm" variant="light" color={color} tt="none" radius="sm">
              {row.site}
            </Badge>
          ))}
        </Group>
      )}
    </Stack>
  );
}

function FailedSiteRow({ row }: { row: SiteOutcomeRecord }) {
  const { t } = useTranslation("tasks");
  // 原因/状态码/详情均为结构化字段, 不做任何文本解析.
  const reasonText = row.reason != null ? t(`report.reason.${row.reason}`) : null;
  const statusText = row.http_status != null ? `HTTP ${row.http_status}` : null;
  const primary = reasonText ?? statusText ?? row.detail ?? t("report.detail.unknown");
  const suffix = row.detail && (reasonText || statusText) ? ` · ${row.detail}` : "";

  return (
    <Group gap="xs" wrap="nowrap" align="baseline">
      <Text size="sm" ff="monospace" style={{ flexShrink: 0, minWidth: "4.5rem" }}>
        {row.site}
      </Text>
      <Text size="sm" c="dimmed" style={{ wordBreak: "break-word" }}>
        {primary}
        {suffix}
      </Text>
    </Group>
  );
}

function groupByOutcome(
  outcomes: SiteOutcomeRecord[],
): { kind: SiteOutcomeKind; rows: SiteOutcomeRecord[] }[] {
  const buckets: Record<SiteOutcomeKind, SiteOutcomeRecord[]> = {
    blocked: [],
    failed: [],
    ok: [],
    cache_hit: [],
  };
  for (const row of outcomes) {
    buckets[row.outcome].push(row);
  }
  return SITE_OUTCOME_KINDS.filter((kind) => buckets[kind].length > 0).map((kind) => ({
    kind,
    rows: buckets[kind].toSorted((a, b) => a.site.localeCompare(b.site)),
  }));
}

function outcomeColor(outcome: SiteOutcomeKind): string {
  switch (outcome) {
    case "blocked":
      return "orange";
    case "failed":
      return "red";
    case "ok":
      return "green";
    case "cache_hit":
      return "gray";
    default:
      return assertNever(outcome);
  }
}

function outcomeIcon(outcome: SiteOutcomeKind) {
  switch (outcome) {
    case "blocked":
    case "failed":
      return <IconAlertCircle size={12} />;
    case "ok":
      return <IconCheck size={12} />;
    case "cache_hit":
      return <IconDatabase size={12} />;
    default:
      return assertNever(outcome);
  }
}
