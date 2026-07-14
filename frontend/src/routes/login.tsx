import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { LoginPage } from "@/components/asm/LoginPage";

export const Route = createFileRoute("/login")({
  component: LoginRoute,
});

function LoginRoute() {
  const navigate = useNavigate();

  const handleLogin = () => {
    navigate({ to: "/" });
  };

  return <LoginPage onLogin={handleLogin} />;
}
