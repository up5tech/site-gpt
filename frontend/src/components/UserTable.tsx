import { useAuth } from '@/context/AuthContext';
import { User } from '@/types/api';
import { getCompanyUsers } from '@/utils/api';
import Table, { ColumnsType } from 'antd/es/table';
import { useEffect, useState } from 'react';

export function UserTable() {
  const { isAuthenticated } = useAuth();

  const [loading, setLoading] = useState<boolean>(false);
  const [users, setUsers] = useState<any>([]);
  const [total, setTotal] = useState<number>(0);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const res = await getCompanyUsers({ page: 1, limit: 100 });
      setUsers(res.data?.items);
      setTotal(res.data?.total);
    } catch (error) {
      console.error('Fetch users error', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isAuthenticated) return;
    fetchUsers();
  }, []);

  const columns: ColumnsType<User> = [
    {
      title: 'Email',
      dataIndex: 'email',
      key: 'email',
    },
    {
      title: 'Phone',
      dataIndex: 'phone',
      key: 'phone',
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
    },
    {
      title: 'First Name',
      dataIndex: 'first_name',
      key: 'first_name',
    },
    {
      title: 'Last Name',
      dataIndex: 'last_name',
      key: 'last_name',
    },
    {
      title: 'Role',
      dataIndex: 'role',
      key: 'role',
    },
  ];

  return (
    <>
      <Table
        columns={columns}
        dataSource={users}
        loading={loading}
        rowKey='id'
      />
    </>
  );
}
