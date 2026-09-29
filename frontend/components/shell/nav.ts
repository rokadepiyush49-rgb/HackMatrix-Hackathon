import {
  Activity,
  BookOpenCheck,
  Boxes,
  BriefcaseBusiness,
  CheckCheck,
  Database,
  Factory,
  FileQuestion,
  FileStack,
  FlaskConical,
  History,
  Landmark,
  Library,
  Network,
  Radar,
  ReceiptText,
  Scale,
  ScanSearch,
  ScrollText,
  ShieldCheck,
  Siren,
  UserCog,
  Waypoints,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  badge?: "p1" | "queued";
}
export interface NavSection {
  title: string | null;
  items: NavItem[];
}

export const NAV: NavSection[] = [
  { title: null, items: [{ href: "/", label: "Command Center", icon: Radar }] },
  {
    title: "Investigate",
    items: [
      { href: "/cases", label: "Case Desk", icon: BriefcaseBusiness },
      { href: "/signals", label: "Signal Desk", icon: Siren, badge: "queued" },
      { href: "/chains", label: "Chain Explorer", icon: Waypoints },
      { href: "/trail", label: "Money Trail", icon: Activity },
      { href: "/entities", label: "Entity Explorer", icon: ScanSearch },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { href: "/alibi", label: "Alibi Ledger", icon: ReceiptText },
      { href: "/network", label: "Risk Network", icon: Network },
      { href: "/mule", label: "Mule Factory", icon: Factory },
      { href: "/replay", label: "Timeline Replay", icon: History },
    ],
  },
  { title: "Council", items: [{ href: "/council", label: "Investigation Council", icon: Landmark, badge: "p1" }] },
  {
    title: "Evidence",
    items: [
      { href: "/evidence", label: "Evidence Packs", icon: FileStack },
      { href: "/evidence/arguments", label: "Prosecution & Defence", icon: Scale },
      { href: "/evidence/missing", label: "Missing Evidence", icon: FileQuestion },
      { href: "/audit", label: "Audit Trail", icon: ScrollText },
    ],
  },
  {
    title: "Prevent",
    items: [
      { href: "/controls", label: "Control Lab", icon: ShieldCheck },
      { href: "/lab", label: "Twin Scenario Lab", icon: FlaskConical },
      { href: "/controls/library", label: "Control Library", icon: Library },
    ],
  },
  {
    title: "Governance",
    items: [
      { href: "/governance/users", label: "Users & Roles", icon: UserCog },
      { href: "/governance/registry", label: "Agents, Models & Rules", icon: Boxes },
      { href: "/governance/approvals", label: "Approvals", icon: CheckCheck },
      { href: "/governance/sources", label: "Data Sources", icon: Database },
      { href: "/governance/policy", label: "Responsible AI", icon: BookOpenCheck },
    ],
  },
];

export const ALL_ITEMS = NAV.flatMap((s) => s.items);
