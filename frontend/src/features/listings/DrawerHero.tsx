import { Box, Flex, Text } from "@mantine/core";

import type { PropertyImage } from "./api";
import { DrawerImageGallery } from "./DrawerImageGallery";
import { formatScore, scoreBand, scoreColor, scoreLabel } from "./scoreBands";
import classes from "./DrawerHero.module.css";

export function DrawerHero({images, imagesLoading, score, allIn, estimated, bedsBaths }: {
  images: PropertyImage[]; imagesLoading: boolean;
  score: number | null; allIn: number | null; estimated: number | null; bedsBaths: string | null;
}) {
  const band = score === null ? null : scoreColor(score).replace("score", "").toLowerCase();
  return (
    <Box className={classes.hero}>
      {/* <Text className={classes.eyebrow} tt="uppercase" fw={600} c="dimmed">Listing</Text>
      <Title order={3} className={classes.title}>{name}</Title>
      <Group gap={7} wrap="nowrap" className={classes.addr}>
        <IconMapPin size={13} stroke={2} />
        {address}
      </Group> */}
      <Box className={classes.gallery}>
        <DrawerImageGallery images={images} loading={imagesLoading} />
      </Box>
      <Box className={classes.stats}>
        {score === null ? (
          <Text className={`${classes.stat} ${classes.notScored}`} c="dimmed">Not scored yet</Text>
        ) : (
          <Flex direction="column" justify="center" className={classes.scoreStat} data-band={band}>
            <Box className={classes.scoreNum}>
              {formatScore(score)}<small>/15</small>
              {scoreBand(score) === 0 && <span className={classes.exc}>✦</span>}
            </Box>
            <Text className={classes.matchTag}>{scoreLabel(score)}</Text>
          </Flex>
        )}
        <Flex direction="column" justify="center" className={classes.stat}>
          <Text className={classes.statLabel} tt="uppercase" fw={600} c="dimmed">All-in / mo</Text>
          <Text className={classes.statBig}>{allIn === null ? "—" : `$${allIn.toLocaleString()}`}</Text>
          {estimated ? (
            <Text className={classes.statSub} c="dimmed">~${estimated.toLocaleString()} estimated</Text>
          ) : null}
        </Flex>
        <Flex direction="column" justify="center" className={classes.stat}>
          <Text className={classes.statLabel} tt="uppercase" fw={600} c="dimmed">Home</Text>
          <Text className={classes.statBig}>{bedsBaths ?? "—"}</Text>
        </Flex>
      </Box>
    </Box>
  );
}
