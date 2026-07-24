import { Card, Group, Title } from "@mantine/core";
import type { ReactNode } from "react";
import classes from "./SectionCard.module.css";

export function SectionCard({ title, hint, children }: {
  title: string; hint?: ReactNode; children: ReactNode;
}) {
  return (
    <Card className={classes.card} padding={0}>
      <Group className={classes.head} justify="space-between" wrap="nowrap">
        <Title order={5} className={classes.title}>{title}</Title>
        {hint != null && <span className={classes.hint}>{hint}</span>}
      </Group>
      <div className={classes.body}>{children}</div>
    </Card>
  );
}
