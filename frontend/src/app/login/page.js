import LoginForm from '@/components/auth/LoginForm';

export const metadata = {
  title: 'Login | JSL Client Portal',
};

export default function LoginPage() {
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <LoginForm />
    </div>
  );
}
