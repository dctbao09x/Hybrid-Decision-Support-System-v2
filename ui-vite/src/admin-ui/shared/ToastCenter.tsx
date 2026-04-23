import { useAdminStore } from '../store/AdminStoreProvider';

export function ToastCenter() {
  const { notificationQueue, dismissNotification } = useAdminStore();

  return (
    <div className="admin-toast-center" aria-live="polite">
      {notificationQueue.slice(-4).map((item) => (
        <button
          key={item.id}
          type="button"
          className={`admin-toast admin-toast-${item.level}`}
          onClick={() => dismissNotification(item.id)}
        >
          {item.message}
        </button>
      ))}
    </div>
  );
}
