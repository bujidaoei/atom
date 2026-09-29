import { useTheme } from "../lib/theme";
import { IconButton } from "./ui/Button";
import { Icon } from "./ui/Icon";

export function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const nextLabel = theme === "dark" ? "切换到亮色" : "切换到暗色";
  return (
    <IconButton label={nextLabel} onClick={toggle} className={className}>
      <Icon name={theme === "dark" ? "sun" : "moon"} size={15} />
    </IconButton>
  );
}
