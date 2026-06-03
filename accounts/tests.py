'''Tests for authentication flows and dashboard access control.'''

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class AuthenticationFlowTests(TestCase):
    '''Cover login, logout and registration through the public CBVs.'''

    def setUp(self):
        self.password = 'StrongPass123!'
        self.user = User.objects.create_user(
            username='ada.lovelace',
            email='ada@example.com',
            password=self.password,
        )

    def test_login_page_renders(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Entrar')

    def test_login_with_valid_credentials_redirects_to_dashboard(self):
        response = self.client.post(
            reverse('accounts:login'),
            data={'username': self.user.username, 'password': self.password},
        )
        self.assertRedirects(response, reverse('accounts:dashboard'))

    def test_login_with_invalid_credentials_keeps_user_anonymous(self):
        response = self.client.post(
            reverse('accounts:login'),
            data={'username': self.user.username, 'password': 'wrong-pass'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['user'].is_authenticated)

    def test_logout_redirects_to_login(self):
        self.client.login(username=self.user.username, password=self.password)
        response = self.client.post(reverse('accounts:logout'))
        self.assertRedirects(response, reverse('accounts:login'))

    def test_register_page_renders(self):
        response = self.client.get(reverse('accounts:register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Criar conta')

    def test_register_creates_user_and_signs_in(self):
        response = self.client.post(
            reverse('accounts:register'),
            data={
                'username': 'grace.hopper',
                'email': 'grace@example.com',
                'password1': 'AnotherStrong!42',
                'password2': 'AnotherStrong!42',
            },
        )
        self.assertRedirects(response, reverse('accounts:dashboard'))
        created = User.objects.get(username='grace.hopper')
        self.assertEqual(created.email, 'grace@example.com')
        self.assertEqual(int(self.client.session['_auth_user_id']), created.pk)

    def test_register_rejects_password_mismatch(self):
        response = self.client.post(
            reverse('accounts:register'),
            data={
                'username': 'mismatch.user',
                'email': 'mismatch@example.com',
                'password1': 'AnotherStrong!42',
                'password2': 'DifferentPass!42',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='mismatch.user').exists())

    def test_authenticated_user_is_redirected_away_from_register(self):
        self.client.login(username=self.user.username, password=self.password)
        response = self.client.get(reverse('accounts:register'))
        self.assertRedirects(response, reverse('accounts:dashboard'))


class DashboardAccessTests(TestCase):
    '''Ensure the Painel is restricted to authenticated users.'''

    def setUp(self):
        self.password = 'StrongPass123!'
        self.user = User.objects.create_user(
            username='alan.turing',
            email='alan@example.com',
            password=self.password,
        )
        self.dashboard_url = reverse('accounts:dashboard')

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.dashboard_url)
        login_url = reverse('accounts:login')
        self.assertRedirects(response, f'{login_url}?next={self.dashboard_url}')

    def test_authenticated_user_can_see_dashboard(self):
        self.client.login(username=self.user.username, password=self.password)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Painel')

    def test_dashboard_shows_empty_state_when_user_has_no_calculations(self):
        self.client.login(username=self.user.username, password=self.password)
        response = self.client.get(self.dashboard_url)
        self.assertContains(response, 'Você ainda não realizou cálculos')

    def test_root_url_redirects_to_dashboard(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith(self.dashboard_url))
