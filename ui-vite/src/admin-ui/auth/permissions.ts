export function hasAllPermissions(owned: string[], required: string[]) {
  if (!required.length) return true;
  if (owned.includes('*') || owned.includes('admin:*')) return true;
  return required.every((permission) => {
    const alternatives = permission.split('|').map((item) => item.trim()).filter(Boolean);
    if (!alternatives.length) return true;
    return alternatives.some((candidate) => owned.includes(candidate));
  });
}
