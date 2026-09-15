import {
  ArrowRightStartOnRectangleIcon,
  ChartBarSquareIcon,
  ChevronDownIcon,
  Cog6ToothIcon,
  MapIcon,
  QuestionMarkCircleIcon,
  ShieldCheckIcon,
} from "@heroicons/react/24/outline";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { Me } from "@/common/types/api";
import { AsyncButton } from "@/components/ui";


const ROLE_LABELS: Record<string, string> = {
  docai_viewers: "Viewer",
  docai_operators: "Operator",
  docai_reviewers: "Reviewer",
  docai_approvers: "Approver",
};

export function AccountMenu({ user, pending, onLogout, onStartTour }: {
  user: Me | null;
  pending: boolean;
  onLogout: () => void | Promise<void>;
  onStartTour: () => void;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const username = user?.username || "Account";
  const initial = username.trim().charAt(0).toUpperCase() || "A";
  const access = user?.is_staff
    ? "Administrator"
    : user?.roles.map((role) => ROLE_LABELS[role]).filter(Boolean).join(" · ") || "Platform user";

  function close() {
    if (menu.current && typeof menu.current.hidePopover === "function") {
      menu.current.hidePopover();
    }
  }

  async function logout() {
    await onLogout();
    close();
  }

  function startTour() {
    close();
    trigger.current?.focus();
    requestAnimationFrame(onStartTour);
  }

  return (
    <div className="min-w-0">
      <button
        ref={trigger}
        id="tour-account-menu"
        type="button"
        className="btn btn-ghost btn-sm max-w-52 gap-2"
        popoverTarget="account-menu"
        style={{ anchorName: "--account-menu-anchor" }}
        aria-controls="account-menu"
        aria-expanded={open}
        aria-label={`Account menu for ${username}`}
      >
        <span className="avatar avatar-placeholder" aria-hidden="true">
          <span className="grid size-7 place-items-center rounded-full bg-base-300 text-caption font-semibold">{initial}</span>
        </span>
        <span className="hidden min-w-0 max-w-32 truncate sm:inline" title={username}>{username}</span>
        <ChevronDownIcon className={`size-4 shrink-0 motion-safe:transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      <ul
        ref={menu}
        id="account-menu"
        popover="auto"
        className="dropdown dropdown-end menu elevation-overlay z-50 mt-2 w-64 max-w-[calc(100vw-2rem)] rounded-box border border-base-300 bg-base-100 p-2 text-sm text-base-content"
        style={{ positionAnchor: "--account-menu-anchor" }}
        aria-label="Account menu"
        onToggle={(event) => setOpen(event.currentTarget.matches(":popover-open"))}
      >
        <li className="menu-title px-3 py-2">
          <span className="block min-w-0">
            <span className="block truncate font-semibold text-base-content" title={username}>{username}</span>
            <span className="mt-0.5 block whitespace-normal text-caption font-normal text-secondary">{access}</span>
          </span>
        </li>
        <li><button type="button" onClick={startTour}><MapIcon className="size-4" aria-hidden="true" />Take a tour</button></li>
        <li><Link to="/settings" onClick={close}><Cog6ToothIcon className="size-4" aria-hidden="true" />Settings</Link></li>
        {user?.is_staff && <li><a href="/admin/" onClick={close}><ShieldCheckIcon className="size-4" aria-hidden="true" />Admin</a></li>}
        {user?.is_staff && user.tools.request_profiler && <li><a href={user.tools.request_profiler} onClick={close}><ChartBarSquareIcon className="size-4" aria-hidden="true" />Request profiler</a></li>}
        <li><a href="/api/docs/" onClick={close}><QuestionMarkCircleIcon className="size-4" aria-hidden="true" />API documentation</a></li>
        <li className="mt-1 border-t border-base-300 pt-1">
          <AsyncButton className="w-full justify-start" pending={pending} pendingLabel="Logging out…" onClick={() => void logout()}>
            <span className="inline-flex items-center gap-2"><ArrowRightStartOnRectangleIcon className="size-4" aria-hidden="true" />Log out</span>
          </AsyncButton>
        </li>
      </ul>
    </div>
  );
}
