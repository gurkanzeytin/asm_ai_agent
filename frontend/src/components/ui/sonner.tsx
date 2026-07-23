import { Toaster as Sonner } from "sonner";

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      className="toaster group"
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:rounded-xl group-[.toaster]:border-border/70 group-[.toaster]:bg-background/95 group-[.toaster]:text-foreground group-[.toaster]:shadow-[0_14px_36px_-24px_rgb(15_23_42/0.18)] group-[.toaster]:backdrop-blur-xl",
          success: "group-[.toaster]:border-cyan/20 group-[.toaster]:bg-background/95",
          icon: "group-[.toast]:text-cyan group-[.toast]:opacity-90",
          title: "group-[.toast]:text-[13px] group-[.toast]:font-semibold",
          description: "group-[.toast]:text-[11px] group-[.toast]:text-muted-foreground",
          actionButton: "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton: "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
