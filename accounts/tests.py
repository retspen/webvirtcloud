from django.contrib.auth.models import Permission, User
from django.shortcuts import reverse
from django.test import Client, TestCase


class AccountsTestCase(TestCase):
    def setUp(self):
        self.client.login(username='admin', password='admin')
        user = User.objects.create_user(username='test', password='test')
        permission = Permission.objects.get(codename='change_password')
        user.user_permissions.add(permission)

    def test_profile(self):
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse('account', args=[2]))
        self.assertEqual(response.status_code, 200)

    def test_login_logout(self):
        user = User.objects.get(username='test')
        self.assertEqual(user.id, 2)

        client = Client()

        response = client.post(reverse('login'), {'username': 'test', 'password': 'test'})
        self.assertRedirects(response, reverse('profile'))

        response = client.get(reverse('logout'))
        self.assertRedirects(response, reverse('login'))

    def test_password_change(self):
        client = Client()

        logged_in = client.login(username='test', password='test')
        self.assertTrue(logged_in)

        response = client.get(reverse('change_password'))
        self.assertEqual(response.status_code, 200)

        response = client.post(
            reverse('change_password'),
            {
                'old_password': 'wrongpass',
                'new_password1': 'newpw',
                'new_password2': 'newpw',
            },
        )
        self.assertEqual(response.status_code, 200)

        response = client.post(
            reverse('change_password'),
            {
                'old_password': 'test',
                'new_password1': 'newpw',
                'new_password2': 'newpw',
            },
        )
        self.assertRedirects(response, reverse('profile'))

        client.logout()

        logged_in = client.login(username='test', password='newpw')
        self.assertTrue(logged_in)
