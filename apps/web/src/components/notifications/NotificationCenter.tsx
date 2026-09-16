import { Link } from "react-router-dom";
import { useNotifications } from "../../providers/NotificationProvider";

export function NotificationCenter() {
  const { notifications, unreadCount, markRead, markAllRead } = useNotifications();

  return (
    <details className="notification-center">
      <summary aria-label={`Notifications, ${unreadCount} unread`}>
        Alerts{unreadCount ? ` (${unreadCount})` : ""}
      </summary>
      <div className="notification-panel" role="region" aria-label="Notification list">
        <div className="notification-actions">
          <button type="button" onClick={markAllRead}>
            Mark all read
          </button>
          <Link to="/workspace" className="org-switch-link">
            Open workspace
          </Link>
        </div>
        {notifications.length === 0 ? (
          <p className="muted">No notifications</p>
        ) : (
          <ul>
            {notifications.slice(0, 12).map((item) => (
              <li key={item.id} className={item.status === "unread" ? "unread" : undefined}>
                <strong>{item.title || "Process notification"}</strong>
                <p className="notif-summary">
                  {item.summary || item.body_preview || item.body}
                </p>
                <p className="muted tight">
                  To {(item.to || []).join(", ") || item.display_name || "internal"}
                  {item.process_name ? ` · ${item.process_name}` : ""}
                  {item.email_status ? ` · email ${item.email_status}` : ""}
                </p>
                {item.status === "unread" ? (
                  <button type="button" onClick={() => markRead(item.id)}>
                    Mark read
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}
