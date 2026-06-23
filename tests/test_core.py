import unittest

from database import DormiXRepository
from main import choose_laundry_winner, find_barter_loops, settle_debts


class DormiXCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = DormiXRepository(":memory:")
        self.alice = self.repo.create_user("alice", "token-alice")
        self.bob = self.repo.create_user("bob", "token-bob")
        self.charlie = self.repo.create_user("charlie", "token-charlie")

    def tearDown(self) -> None:
        self.repo.close()

    def test_settlement_uses_approved_debts_only(self) -> None:
        self.repo.add_debt(self.bob.id, self.alice.id, 50.0, "approved chai", "approved")
        self.repo.add_debt(self.alice.id, self.bob.id, 999.0, "pending trap", "pending")

        self.assertEqual(settle_debts(self.repo), [(self.bob.id, self.alice.id, 50.0)])

    def test_laundry_lowest_vruntime_weight_score_wins(self) -> None:
        self.repo.add_laundry_job(self.alice.id, vruntime=2.0, weight=1.0)
        self.repo.add_laundry_job(self.bob.id, vruntime=3.0, weight=3.0)

        winner = choose_laundry_winner(self.repo, runtime_increment=1.0)

        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner[0].user_id, self.bob.id)

    def test_barter_finds_depth_three_cycle(self) -> None:
        self.repo.add_barter_node(self.alice.id, 1, 2)
        self.repo.add_barter_node(self.bob.id, 2, 3)
        self.repo.add_barter_node(self.charlie.id, 3, 1)

        loops = find_barter_loops(self.repo)

        self.assertEqual(len(loops), 1)
        self.assertEqual([entry[0] for entry in loops[0]], [self.alice.id, self.bob.id, self.charlie.id])


if __name__ == "__main__":
    unittest.main()
