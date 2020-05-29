from django.contrib.auth.models import User
from django.shortcuts import reverse
from django.test import Client, TestCase


class AccountsTestCase(TestCase):
    def setUp(self):
        self.client.login(username='admin', password='admin')
        User.objects.create_user(username='test', password='test')

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
