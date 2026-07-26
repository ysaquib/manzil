// Per-criterion icon and hued icon tile for the rubric page (view + edit cards).
// Resolves a Tabler icon for a catalog entry: specific by key, then by category,
// then a generic fallback. Kept data-driven and shared so the two card
// components never drift. Icons are decorative — the label carries meaning — so
// they render aria-hidden (DESIGN §13.2).
//
// The tile's hue comes from the criterion's category (criterionCategory.ts) and
// is identity, never status (UI Decision Log 2026-07-25).
import { ThemeIcon } from "@mantine/core";
import {
  IconArmchair,
  IconBarbell,
  IconBath,
  IconBed,
  IconBuildingCommunity,
  IconBuildingSkyscraper,
  IconCalendarEvent,
  IconCalendarStats,
  IconCar,
  IconCash,
  IconClipboardText,
  IconCoins,
  IconCreditCard,
  IconDeviceMobileMessage,
  IconDoorEnter,
  IconFence,
  IconGlassFull,
  IconHammer,
  IconHome,
  IconLayoutGrid,
  IconListCheck,
  IconMapPin,
  IconPackage,
  IconPaw,
  IconPool,
  IconReceipt,
  IconRuler,
  IconShield,
  IconShoppingCart,
  IconSmoking,
  IconSnowflake,
  IconStar,
  IconTexture,
  IconThumbUp,
  IconTool,
  IconToolsKitchen2,
  IconUrgent,
  IconUserCheck,
  IconWashMachine,
  IconWifi,
} from "@tabler/icons-react";

import type { CatalogEntry } from "./api";
import { categoryColor } from "./criterionCategory";

type TablerIcon = typeof IconBed;

// Specific icon per catalog key. Every seeded key gets its own glyph — a
// category fallback repeated across a whole tranche reads as a rendering bug
// once the icons sit in tinted tiles.
const BY_KEY: Record<string, TablerIcon> = {
  // Property
  clubhouse: IconArmchair,
  pool: IconPool,
  fitness_center: IconBarbell,
  maintenance_on_site: IconHammer,
  emergency_maintenance: IconUrgent,
  management_on_site: IconUserCheck,
  online_payments: IconCreditCard,
  online_maintenance_requests: IconDeviceMobileMessage,
  package_handling: IconPackage,
  smoking_policy: IconSmoking,
  internet_readiness: IconWifi,
  property_types: IconBuildingSkyscraper,
  // Floor plan and unit
  beds: IconBed,
  baths: IconBath,
  sqft: IconRuler,
  patio_balcony: IconFence,
  private_entry: IconDoorEnter,
  in_unit_laundry: IconWashMachine,
  parking: IconCar,
  cooling: IconSnowflake,
  dishwasher: IconGlassFull,
  unit_types: IconLayoutGrid,
  // Policies
  pets_policy: IconPaw,
  min_lease_months: IconCalendarStats,
  // Costs
  all_in_monthly: IconCash,
  security_deposit: IconCoins,
  // Availability
  availability_date: IconCalendarEvent,
  // Condition
  kitchen_quality: IconToolsKitchen2,
  flooring_quality: IconTexture,
  // Location
  grocery_proximity: IconShoppingCart,
  location_safety: IconShield,
  // Reputation
  management_reviews: IconStar,
};

// Fallback per category (CriterionCategory), for any future/unknown key. Each
// is an icon no seeded key uses, so a missing BY_KEY entry is visible rather
// than disguised as a real one.
const BY_CATEGORY: Record<string, TablerIcon> = {
  unit: IconHome,
  cost: IconReceipt,
  tenancy: IconClipboardText,
  location: IconMapPin,
  fittings: IconTool,
  amenities: IconBuildingCommunity,
  management: IconThumbUp,
};

export function criterionIconFor(entry: Pick<CatalogEntry, "key" | "category">): TablerIcon {
  return BY_KEY[entry.key] ?? BY_CATEGORY[entry.category] ?? IconListCheck;
}

/**
 * The criterion's icon in its category hue — the rubric card's identity mark.
 * `light` fills a tile (cards); `transparent` is the bare glyph (add-pills).
 */
export function CriterionTile({
  entry,
  size = 26,
  variant = "light",
}: {
  entry: Pick<CatalogEntry, "key" | "category">;
  size?: number;
  variant?: "light" | "transparent";
}) {
  const Icon = criterionIconFor(entry);
  return (
    <ThemeIcon
      variant={variant}
      radius="sm"
      size={size}
      color={categoryColor(entry.category)}
      aria-hidden
    >
      <Icon size={Math.round(size * 0.62)} stroke={1.5} />
    </ThemeIcon>
  );
}
