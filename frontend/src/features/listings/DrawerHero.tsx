import { Title } from "@mantine/core";
import { IconMapPin } from "@tabler/icons-react";
import type { PropertyImage } from "./api";
import { DrawerImageGallery } from "./DrawerImageGallery";
import { formatScore, scoreBand, scoreColor, scoreLabel } from "./scoreBands";
import classes from "./DrawerHero.module.css";

export function DrawerHero({ name, address, images, imagesLoading, score, allIn, estimated, bedsBaths }: {
  name: string; address: string; images: PropertyImage[]; imagesLoading: boolean;
  score: number | null; allIn: number | null; estimated: number | null; bedsBaths: string | null;
}) {
  const band = score === null ? null : scoreColor(score).replace("score", "").toLowerCase();
  return (
    <div className={classes.hero}>
      <div className={classes.eyebrow}>Listing</div>
      <Title order={3} className={classes.title}>{name}</Title>
      <div className={classes.addr}><IconMapPin size={13} stroke={2} /> {address}</div>
      <div className={classes.gallery}><DrawerImageGallery images={images} loading={imagesLoading} /></div>
      <div className={classes.stats}>
        {score === null ? (
          <div className={`${classes.stat} ${classes.notScored}`}>Not scored yet</div>
        ) : (
          <div className={classes.scoreStat} data-band={band}>
            <div className={classes.scoreNum}>
              {formatScore(score)}<small>/15</small>{scoreBand(score) === 0 && <span className={classes.exc}>✦</span>}
            </div>
            <div className={classes.matchTag}>{scoreLabel(score)}</div>
          </div>
        )}
        <div className={classes.stat}>
          <div className={classes.statLabel}>All-in / mo</div>
          <div className={classes.statBig}>{allIn === null ? "—" : `$${allIn.toLocaleString()}`}</div>
          {estimated ? <div className={classes.statSub}>~${estimated.toLocaleString()} estimated</div> : null}
        </div>
        <div className={classes.stat}>
          <div className={classes.statLabel}>Home</div>
          <div className={classes.statBig}>{bedsBaths ?? "—"}</div>
        </div>
      </div>
    </div>
  );
}
