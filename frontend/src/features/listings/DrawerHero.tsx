import { Box, Flex, Text } from "@mantine/core";

import type { PropertyImage } from "./api";
import { DrawerImageGallery } from "./DrawerImageGallery";
import { formatScore, scoreBand, scoreColor, scoreLabel } from "./scoreBands";
import classes from "./DrawerHero.module.css";
import drawer from "./ListingDetailDrawer.module.css";

export function DrawerHero({images, imagesLoading, score, allIn, estimated, bedsBaths }: {
  images: PropertyImage[]; imagesLoading: boolean;
  score: number | null; allIn: number | null; estimated: number | null; bedsBaths: string | null;
}) {
  const band = score === null ? null : scoreColor(score).replace("score", "").toLowerCase();
  return (
    <Box className={classes.hero}>
      <Box className={classes.gallery}>
        <DrawerImageGallery images={images} loading={imagesLoading} />
      </Box>
      <Box className={classes.stats}>
        {score === null ? (
          <Text className={`${classes.stat} ${classes.notScored}`} c="dimmed">Not scored yet</Text>
        ) : (
          <Flex direction="column" justify="center" className={classes.scoreStat} data-band={band}>
            <Box className={`${classes.scoreNum} ${drawer.bandText}`} data-band={band}>
              {formatScore(score)}
              <Text
                component="span"
                className={`${classes.scoreDenom} ${drawer.bandText}`}
                data-band={band}
              >
                /15
              </Text>
              {scoreBand(score) === 0 && (
                <Text component="span" className={drawer.drawerExcMark}>
                  ✦
                </Text>
              )}
            </Box>
            <Text className={`${classes.matchTag} ${drawer.bandText}`} data-band={band}>
              {scoreLabel(score)}
            </Text>
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
