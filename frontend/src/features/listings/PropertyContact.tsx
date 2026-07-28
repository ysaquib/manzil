// Contact (P3-21, §13.2): how to reach the leasing office, inside the Location
// card. The card already answers "where is this?", so "how do I reach them?"
// belongs with it rather than in a card of its own.
//
// Renders nothing when no contact is known. That is the designed give-up state
// (§20 2026-07-27), not an omission: the Sources card and the property's official
// link are already on screen, so an empty-state row would add noise without
// telling the reader anything they cannot already act on.
import { Anchor, Group, Stack, Text } from "@mantine/core";
import { IconExternalLink, IconPhone } from "@tabler/icons-react";

import { usePropertyContacts, type PropertyContact as Contact } from "./api";

// Where the value came from, in the reader's words. Shown because a Places
// number and an official-site number are not equally trustworthy, and the
// reader deserves to know which one they are about to dial.
const PROVENANCE_LABEL: Record<Contact["provenance"], string> = {
  official_site: "from official site",
  google_places: "from Google",
  listing: "from listing",
};

// `tel:` wants digits, not the display formatting.
function telHref(value: string): string {
  return `tel:${value.replace(/[^\d+]/g, "")}`;
}

export function PropertyContactRow({ propertyId }: { propertyId: string }) {
  const { data: contacts } = usePropertyContacts(propertyId);
  if (!contacts || contacts.length === 0) return null;

  const phone = contacts.find((c) => c.kind === "phone");
  const contactUrl = contacts.find((c) => c.kind === "contact_url");

  return (
    <Stack gap={4}>
      {phone && (
        <Group gap="xs" wrap="nowrap">
          <IconPhone size={15} stroke={1.6} />
          <Anchor href={telHref(phone.value)} size="sm">
            {phone.value}
          </Anchor>
          <Text size="xs" c="dimmed">
            {PROVENANCE_LABEL[phone.provenance]}
          </Text>
        </Group>
      )}
      {contactUrl && (
        <Group gap="xs" wrap="nowrap">
          <IconExternalLink size={15} stroke={1.6} />
          <Anchor href={contactUrl.value} target="_blank" rel="noreferrer" size="sm">
            Contact page
          </Anchor>
          <Text size="xs" c="dimmed">
            {PROVENANCE_LABEL[contactUrl.provenance]}
          </Text>
        </Group>
      )}
    </Stack>
  );
}
