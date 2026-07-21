// Muted per-criterion icon for the rubric page (view + edit cards). Resolves an
// appropriate Tabler icon for a catalog entry: specific by key, then by
// category, then a generic fallback. Kept data-driven and shared so the two
// card components never drift. Icons are decorative — the label carries meaning
// — so they render aria-hidden in a single dimmed tone (DESIGN §13.2).
import {
  IconBath,
  IconBed,
  IconCalendar,
  IconCalendarEvent,
  IconCalendarStats,
  IconCar,
  IconCash,
  IconClipboardText,
  IconCoins,
  IconDoorEnter,
  IconFence,
  IconGlassFull,
  IconHome,
  IconListCheck,
  IconMapPin,
  IconPaw,
  IconRuler,
  IconShield,
  IconShoppingCart,
  IconSnowflake,
  IconStar,
  IconTexture,
  IconToolsKitchen2,
  IconTool,
  IconWashMachine,
} from "@tabler/icons-react";

import type { CatalogEntry } from "./api";

type TablerIcon = typeof IconBed;

// Specific icon per catalog key (the 19 seeded criteria).
const BY_KEY: Record<string, TablerIcon> = {
  beds: IconBed,
  baths: IconBath,
  sqft: IconRuler,
  patio_balcony: IconFence,
  private_entry: IconDoorEnter,
  in_unit_laundry: IconWashMachine,
  pets_policy: IconPaw,
  all_in_monthly: IconCash,
  security_deposit: IconCoins,
  availability_date: IconCalendarEvent,
  kitchen_quality: IconToolsKitchen2,
  flooring_quality: IconTexture,
  parking: IconCar,
  cooling: IconSnowflake,
  dishwasher: IconGlassFull,
  min_lease_months: IconCalendarStats,
  grocery_proximity: IconShoppingCart,
  management_reviews: IconStar,
  location_safety: IconShield,
};

// Fallback per category (CriterionCategory), for any future/unknown key.
const BY_CATEGORY: Record<string, TablerIcon> = {
  unit: IconHome,
  policy: IconClipboardText,
  cost: IconCash,
  availability: IconCalendar,
  condition: IconTool,
  location: IconMapPin,
  reputation: IconStar,
};

export function criterionIconFor(entry: Pick<CatalogEntry, "key" | "category">): TablerIcon {
  return BY_KEY[entry.key] ?? BY_CATEGORY[entry.category] ?? IconListCheck;
}

export function CriterionIcon({ entry }: { entry: Pick<CatalogEntry, "key" | "category"> }) {
  const Icon = criterionIconFor(entry);
  return (
    <Icon size={16} stroke={1.5} color="var(--mantine-color-dimmed)" aria-hidden />
  );
}
